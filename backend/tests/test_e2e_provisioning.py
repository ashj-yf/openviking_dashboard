"""端到端：建团队 → 开通 → 登录改密 → 取凭证 → 自助重签 → 停用/启用 → 销户 → 删团队。"""


async def test_full_provisioning_lifecycle(
    client, make_user, auth_headers, ov_calls
):
    platform = await make_user("rootadmin", "Admin#12345", "admin")
    headers = auth_headers(platform)
    ov_calls["responses"].extend([
        (200, {"account_id": "acme", "admin_key": "boss-key-12345678"}),  # create account
        (200, {"user_id": "carol"}),                                      # register（不带 key）
        (200, {"key": "carol-key-12345678"}),                             # issue key
    ])

    create_tenant = await client.post("/api/v1/tenants", json={
        "account_id": "acme",
        "admin_user_id": "boss",
        "admin_username": "bosslogin",
        "admin_password": "Boss#12345",
    }, headers=headers)
    assert create_tenant.status_code == 201
    tenant_id = create_tenant.json()["id"]

    create_user = await client.post("/api/v1/users", json={
        "username": "carol",
        "password": "Carol#1234",
        "tenant_id": tenant_id,
    }, headers=headers)
    assert create_user.status_code == 201, create_user.text
    carol_id = create_user.json()["id"]

    # carol 用初始密码登录；首登强制改密门禁先拦截凭证页
    login = await client.post("/api/v1/auth/login",
                              json={"username": "carol", "password": "Carol#1234"})
    assert login.status_code == 200
    carol_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get("/api/v1/credentials",
                              headers=carol_headers)).status_code == 403
    changed = await client.post("/api/v1/auth/change-password", headers=carol_headers, json={
        "old_password": "Carol#1234",
        "new_password": "Carol#abcde",
    })
    assert changed.status_code == 204
    view = await client.get("/api/v1/credentials", headers=carol_headers)
    assert view.status_code == 200
    assert view.json()["key_masked"]  # 打码非空

    # 自助重签（Q5 默认允许）
    ov_calls["responses"].append((200, {"key": "rotated-key-87654321"}))
    rotated = await client.post("/api/v1/credentials/regenerate", json={},
                                 headers=carol_headers)
    assert rotated.status_code == 200
    assert rotated.json()["key"] == "rotated-key-87654321"

    # 停用 → 持旧 JWT 下一请求立即 401；启用 → 同一 JWT 恢复可用
    assert (await client.post(
        f"/api/v1/users/{carol_id}/disable", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/credentials",
                              headers=carol_headers)).status_code == 401
    assert (await client.post(
        f"/api/v1/users/{carol_id}/enable", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/credentials",
                              headers=carol_headers)).status_code == 200

    # 销户（普通成员）→ 删团队（OV 账户整体回收，本地级联）
    ov_calls["responses"].append((200, {}))  # delete user
    assert (await client.delete(
        f"/api/v1/users/{carol_id}", headers=headers)).status_code == 204
    ov_calls["responses"].append((200, {}))  # delete account
    # httpx 0.28 AsyncClient.delete 不接受 json 参数（R3 裁决：DELETE 带 body 一律 request 写法）
    assert (await client.request(
        "DELETE", f"/api/v1/tenants/{tenant_id}", json={"confirm": True},
        headers=headers)).status_code == 204

    # 全部 OV 调用均为 root key 管理面，零数据面
    assert ov_calls["calls"], "必须有 OV 调用"
    for c in ov_calls["calls"]:
        assert c["path"].startswith("/api/v1/admin/"), c["path"]
        assert c["authorization"] == "Bearer test-root-key"
    # 调用序列：accounts(POST) → users(POST) → key(POST) → key(POST 重签)
    #         → users/{id}(DELETE) → accounts/{id}(DELETE)
    assert [c["path"] for c in ov_calls["calls"]] == [
        "/api/v1/admin/accounts",
        "/api/v1/admin/accounts/acme/users",
        "/api/v1/admin/accounts/acme/users/carol/key",
        "/api/v1/admin/accounts/acme/users/carol/key",
        "/api/v1/admin/accounts/acme/users/carol",
        "/api/v1/admin/accounts/acme",
    ]


async def test_rbac_matrix_across_management_endpoints(
    client, make_user, make_tenant, auth_headers, ov_calls
):
    t = await make_tenant("acme")
    await make_user("rootadmin", "Admin#12345", "admin")
    ta = await make_user("boss", "Passw0rd!", "team_admin",
                          tenant=t, ov_user_id="boss", must_change_password=False)
    u = await make_user("alice", "Passw0rd!", "user", tenant=t,
                         ov_user_id="alice", must_change_password=False)

    # user 对全部管理端点 403（POST 被 _manager 拦截，不触达 OV，无需 mock）
    for method, path, body in [
        ("GET", "/api/v1/tenants", None),
        ("POST", "/api/v1/tenants", {"account_id": "x1", "admin_user_id": "u",
                                      "admin_username": "u", "admin_password": "Passw0rd!"}),
        ("GET", "/api/v1/users", None),
        ("POST", "/api/v1/users", {"username": "z", "password": "Passw0rd!",
                                    "tenant_id": t.id}),
    ]:
        r = await client.request(method, path, json=body, headers=auth_headers(u))
        assert r.status_code == 403, (method, path, r.status_code)

    # team_admin：租户端点 403；用户列表 200
    assert (await client.get("/api/v1/tenants", headers=auth_headers(ta))).status_code == 403
    assert (await client.get("/api/v1/users", headers=auth_headers(ta))).status_code == 200

    # team_admin 跨团队开户被强制收窄到本团队（201，落 t.id）
    t2 = await make_tenant("beta")
    ov_calls["responses"].extend([(200, {}), (200, {"key": "z-key-1234567890"})])
    r = await client.post("/api/v1/users", json={
        "username": "z", "password": "Passw0rd!", "tenant_id": t2.id,
    }, headers=auth_headers(ta))
    assert r.status_code == 201
    assert r.json()["tenant_id"] == t.id
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users"


async def test_openapi_surface(client):
    spec = (await client.get("/openapi.json")).json()
    paths = set(spec["paths"])
    expected = {
        "/api/v1/tenants", "/api/v1/tenants/{tenant_id}",
        "/api/v1/tenants/{tenant_id}/sync",
        "/api/v1/users", "/api/v1/users/{user_id}",
        "/api/v1/users/{user_id}/role",
        "/api/v1/users/{user_id}/reset-password",
        "/api/v1/users/{user_id}/disable",
        "/api/v1/users/{user_id}/enable",
        "/api/v1/users/{user_id}/regenerate-key",
        "/api/v1/users/{user_id}/sync",
        "/api/v1/credentials", "/api/v1/credentials/reveal",
        "/api/v1/credentials/copy", "/api/v1/credentials/regenerate",
    }
    assert expected <= paths
    assert "/api/v1/admin-users/{user_id}/reset-password" not in paths
