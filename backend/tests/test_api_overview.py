"""总览聚合路由：本地 KPI、OV 分节降级、observer 并发与 RBAC。"""

OBSERVER_COMPONENTS = (
    "queue",
    "models",
    "retrieval",
    "system",
    "vikingdb",
    "filesystem",
    "lock",
)


async def test_summary_rbac(client, make_user, make_tenant, auth_headers):
    """user 403；team_admin 本团队计数且全局字段为 None；admin 全字段。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    viewer = await make_user("plain", "Passw0rd!", "user")
    t1 = await make_tenant("ov-t1")
    t2 = await make_tenant("ov-t2")
    ta = await make_user("ta", "Passw0rd!", "team_admin", tenant=t1)
    await make_user("u1", "Passw0rd!", "user", tenant=t1)
    await make_user("u2", "Passw0rd!", "user", tenant=t2, is_active=False)

    r = await client.get("/api/v1/overview/summary", headers=auth_headers(viewer))
    assert r.status_code == 403

    # team_admin：users_* 仅本团队（t1 的 ta+u1），不请求 OV 全局指标
    r = await client.get("/api/v1/overview/summary", headers=auth_headers(ta))
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_count"] is None
    assert body["ov_summary"] is None
    assert body["users_total"] == 2
    assert body["users_active"] == 2
    assert body["users_disabled"] == 0
    # ov_health 全员可见（OVR-2 顶栏健康灯）
    assert body["ov_health"] is not None

    # admin：全字段
    r = await client.get("/api/v1/overview/summary", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_count"] == 2
    assert body["ov_summary"] is not None
    assert body["ov_health"] is not None


async def test_summary_local_counts(client, make_user, make_tenant, auth_headers):
    """admin 视角本地计数：2 团队 5 租户用户（3 启用 2 禁用）。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t1 = await make_tenant("cnt-t1")
    t2 = await make_tenant("cnt-t2")
    await make_user("a1", "Passw0rd!", "user", tenant=t1)
    await make_user("a2", "Passw0rd!", "team_admin", tenant=t1)
    await make_user("a3", "Passw0rd!", "user", tenant=t2)
    await make_user("d1", "Passw0rd!", "user", tenant=t2, is_active=False)
    await make_user("d2", "Passw0rd!", "user", tenant=t1, is_active=False)

    r = await client.get("/api/v1/overview/summary", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_count"] == 2
    assert body["users_total"] == 5
    assert body["users_active"] == 3
    assert body["users_disabled"] == 2


async def test_summary_ov_degrades(client, make_user, make_tenant, auth_headers, ov_calls):
    """OV 全挂时仍 200：本地 KPI 照常，两个 OV 分节显式降级并带错误消息。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t1 = await make_tenant("deg-t1")
    await make_user("u1", "Passw0rd!", "user", tenant=t1)
    ov_calls["responses"].extend(
        [(502, {"detail": "summary-boom"}), (502, {"detail": "health-boom"})]
    )

    r = await client.get("/api/v1/overview/summary", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    # 本地 KPI 不受 OV 故障影响
    assert body["tenant_count"] == 1
    assert body["users_total"] == 1
    assert body["ov_summary"] is None
    assert body["ov_health"] is None
    # ov_error 非空且含两节错误
    assert body["ov_error"]
    assert "summary-boom" in body["ov_error"]
    assert "health-boom" in body["ov_error"]


async def test_observer_admin_only(client, make_user, make_tenant, auth_headers):
    """observer 仅 admin：team_admin 直调被后端拒绝（不靠前端隐藏）。"""
    t1 = await make_tenant("obs-t1")
    ta = await make_user("ta", "Passw0rd!", "team_admin", tenant=t1)
    viewer = await make_user("plain", "Passw0rd!", "user")

    r = await client.get("/api/v1/overview/observer", headers=auth_headers(ta))
    assert r.status_code == 403
    r = await client.get("/api/v1/overview/observer", headers=auth_headers(viewer))
    assert r.status_code == 403


async def test_observer_partial_failure(client, make_user, auth_headers, ov_calls):
    """七组件并发：任一 502 只降级该组件，其余组件原样透传。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ok_payloads = {c: {"component": c, "status": "healthy"} for c in OBSERVER_COMPONENTS}
    ov_calls["responses"].extend(
        [
            (502, {"detail": "queue-boom"}),  # 第 1 个
            (200, ok_payloads["models"]),
            (200, ok_payloads["retrieval"]),
            (502, {"detail": "system-boom"}),  # 第 4 个
            (200, ok_payloads["vikingdb"]),
            (200, ok_payloads["filesystem"]),
            (200, ok_payloads["lock"]),
        ]
    )

    r = await client.get("/api/v1/overview/observer", headers=auth_headers(admin))
    assert r.status_code == 200
    components = r.json()["components"]
    assert set(components) == set(OBSERVER_COMPONENTS)

    for failed, boom in (("queue", "queue-boom"), ("system", "system-boom")):
        assert components[failed]["data"] is None
        assert components[failed]["error"] is not None
        assert boom in components[failed]["error"]
    for name in ("models", "retrieval", "vikingdb", "filesystem", "lock"):
        assert components[name]["data"] == ok_payloads[name]
        assert components[name]["error"] is None


async def test_observer_single_and_unknown(client, make_user, auth_headers, ov_calls):
    """单组件 200 透传（data/error 包装）；未知组件 404 且不触达 OV。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    payload = {"status": "healthy", "depth": 3}
    ov_calls["responses"].append((200, payload))

    r = await client.get("/api/v1/overview/observer/queue", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == payload
    assert body["error"] is None
    assert ov_calls["calls"][0]["path"] == "/api/v1/observer/queue"

    r = await client.get("/api/v1/overview/observer/nope", headers=auth_headers(admin))
    assert r.status_code == 404
    # 未知组件在校验层即拒绝，不产生 OV 调用
    assert len(ov_calls["calls"]) == 1
