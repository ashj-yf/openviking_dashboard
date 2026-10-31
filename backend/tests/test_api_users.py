"""用户开通、列表与生命周期管理路由。"""
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.models import AuditLog, DashboardUser, KeyRecord
from app.services.auth_service import authenticate


async def test_create_user_api_and_no_key_in_response(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov_calls["responses"].extend([
        (200, {"user_id": "carol"}),
        (200, {"key": "user-key-1234567890"}),
    ])
    r = await client.post(
        "/api/v1/users",
        json={"username": "carol", "password": "Carol#1234", "tenant_id": t.id},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201, r.text
    assert "user-key-1234567890" not in r.text
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users"
    assert ov_calls["calls"][1]["path"] == "/api/v1/admin/accounts/acme/users/carol/key"
    assert all(c["authorization"] == "Bearer test-root-key" for c in ov_calls["calls"])


async def test_user_role_cannot_open_users(client, make_user, make_tenant, auth_headers):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    assert (await client.get("/api/v1/users", headers=auth_headers(u))).status_code == 403
    assert (await client.post("/api/v1/users", json={
        "username": "x", "password": "Xxxx#12345", "tenant_id": t.id,
    }, headers=auth_headers(u))).status_code == 403


async def test_team_admin_cross_tenant_create_forced_scoped(
    client, make_user, make_tenant, auth_headers, ov_calls
):
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t1, ov_user_id="boss")
    ov_calls["responses"].extend([(200, {}), (200, {"key": "k-1234567890ab"})])
    r = await client.post(
        "/api/v1/users",
        json={"username": "x", "password": "Xxxx#12345", "tenant_id": t2.id},
        headers=auth_headers(ta),
    )
    assert r.status_code == 201
    assert r.json()["tenant_id"] == t1.id


async def test_list_scoping_and_shape(
    client, make_user, make_tenant, auth_headers
):
    platform = await make_user("rootadmin", "Admin#12345", "admin")
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    await make_user("a1", "Passw0rd!", "user", tenant=t1, ov_user_id="a1", ov_key="key-a-1")
    await make_user("a2", "Passw0rd!", "user", tenant=t1, ov_user_id="a2")
    await make_user("b1", "Passw0rd!", "user", tenant=t2, ov_user_id="b1", ov_key="key-b-1")
    ta = await make_user("boss", "Passw0rd!", "team_admin",
                         tenant=t1, ov_user_id="boss", ov_key="boss-key")

    r = await client.get("/api/v1/users", headers=auth_headers(platform))
    assert r.status_code == 200
    rows = r.json()
    assert {u["username"] for u in rows} == {"rootadmin", "a1", "a2", "b1", "boss"}
    for u in rows:
        assert "ov_user_key_encrypted" not in u
        assert "password_hash" not in u
        assert u["key_state"] in ("current", "pending")
    assert next(u for u in rows if u["username"] == "a1")["key_state"] == "current"
    assert next(u for u in rows if u["username"] == "a2")["key_state"] == "pending"

    r = await client.get("/api/v1/users", headers=auth_headers(ta))
    assert {u["username"] for u in r.json()} == {"a1", "a2", "boss"}

    r = await client.get(
        "/api/v1/users", params={"tenant_id": t2.id}, headers=auth_headers(platform)
    )
    assert {u["username"] for u in r.json()} == {"b1"}


# ---------- USER-3 角色 ----------
async def test_set_role_happy_path(client, db, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_role="user", ov_key="old-key-123")
    ov_calls["responses"].append((200, {}))
    r = await client.patch(
        f"/api/v1/users/{u.id}/role", json={"role": "team_admin"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert u.role == "team_admin"
    assert u.ov_role == "admin"
    call = ov_calls["calls"][0]
    assert call["path"] == "/api/v1/admin/accounts/acme/users/alice/role"
    assert call["body"] == {"role": "admin"}


async def test_set_role_guardrails(client, db, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t, ov_user_id="boss")
    other = await make_user("root2", "Admin#12345", "admin")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")

    # team_admin 无权改席位
    assert (await client.patch(
        f"/api/v1/users/{u.id}/role", json={"role": "team_admin"},
        headers=auth_headers(ta))).status_code == 403
    # 不能改自己
    assert (await client.patch(
        f"/api/v1/users/{admin.id}/role", json={"role": "user"},
        headers=auth_headers(admin))).status_code == 400
    # 平台账号无 OV 角色
    assert (await client.patch(
        f"/api/v1/users/{other.id}/role", json={"role": "team_admin"},
        headers=auth_headers(admin))).status_code == 400
    # 团队最后一个 team_admin 不可降级
    assert (await client.patch(
        f"/api/v1/users/{ta.id}/role", json={"role": "user"},
        headers=auth_headers(admin))).status_code == 409
    assert ov_calls["calls"] == []


async def test_set_role_ov_failure_keeps_local(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    ov_calls["responses"].append((500, {"detail": "boom"}))
    r = await client.patch(
        f"/api/v1/users/{u.id}/role", json={"role": "team_admin"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 500
    await db.refresh(u)
    assert u.role == "user"
    assert u.ov_role == "user"


# ---------- USER-4 重置 + 联动重签 ----------
async def test_reset_password_admin_for_platform_admin(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    other = await make_user("root2", "Admin#12345", "admin")
    r = await client.post(
        f"/api/v1/users/{other.id}/reset-password",
        json={"new_password": "New#123456"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 204
    assert await authenticate(db, "root2", "New#123456") is not None


async def test_reset_password_with_key_rotation(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="old-key-1234567")
    ov_calls["responses"].append((200, {"key": "new-key-76543210"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "New#123456", "regenerate_key": True},
        headers=auth_headers(admin),
    )
    assert r.status_code == 204
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "new-key-76543210"
    assert ov_calls["calls"][0]["path"].endswith("/alice/key")


async def test_team_admin_reset_scope(client, make_user, make_tenant, auth_headers):
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t1, ov_user_id="boss")
    u2 = await make_user("b1", "Passw0rd!", "user", tenant=t2, ov_user_id="b1")
    r = await client.post(
        f"/api/v1/users/{u2.id}/reset-password",
        json={"new_password": "New#123456"},
        headers=auth_headers(ta),
    )
    assert r.status_code == 403


async def test_legacy_admin_users_route_removed(client, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    r = await client.post(
        "/api/v1/admin-users/1/reset-password",
        json={"new_password": "New#123456"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 404


# ---------- USER-5 启停用 ----------
async def test_disable_enable_lifecycle(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    other = await make_user("root2", "Admin#12345", "admin")
    assert (await client.post(
        f"/api/v1/users/{other.id}/disable", headers=auth_headers(admin))).status_code == 204
    await db.refresh(other)
    assert other.is_active is False
    assert (await client.post(
        f"/api/v1/users/{other.id}/enable", headers=auth_headers(admin))).status_code == 204
    await db.refresh(other)
    assert other.is_active is True


async def test_disable_self_blocked(client, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    r = await client.post(f"/api/v1/users/{admin.id}/disable", headers=auth_headers(admin))
    assert r.status_code == 400  # 不能对自己（自我保护先于末位管理员检查）


async def test_team_admin_disable_scope(client, make_user, make_tenant, auth_headers):
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t, ov_user_id="boss")
    r = await client.post(f"/api/v1/users/{ta.id}/disable", headers=auth_headers(ta))
    assert r.status_code == 403


# ---------- 管理员重签 / 半成品补救 ----------
async def test_admin_regenerate_rotates_key_and_records(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="old-key-1234567")
    db.add(KeyRecord(tenant_id=t.id, dashboard_user_id=u.id, ov_user_id="alice",
                     key_kind="user", key_hint="old-key-"))
    await db.commit()
    ov_calls["responses"].append((200, {"api_key": "new-key-76543210"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/regenerate-key", json={}, headers=auth_headers(admin)
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "new-key-76543210"
    recs = (await db.scalars(select(KeyRecord).order_by(KeyRecord.id))).all()
    assert [x.is_current for x in recs] == [False, True]
    assert recs[-1].key_hint == "new-key-"[:8]


async def test_regenerate_revives_half_product(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("erin", "Passw0rd!", "user", tenant=t, ov_user_id="erin",
                         is_active=False)  # Task 4 半成品
    ov_calls["responses"].append((200, {"key": "revive-key-12345"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/regenerate-key", json={}, headers=auth_headers(admin)
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert u.is_active is True
    assert u.ov_user_key_encrypted is not None


async def test_regenerate_ov_failure_keeps_old_key(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="old-key-1234567")
    ov_calls["responses"].append((500, {"detail": "boom"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/regenerate-key", json={}, headers=auth_headers(admin)
    )
    assert r.status_code == 500
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "old-key-1234567"


# ---------- USER-6 销户 ----------
async def test_delete_user_hard_deletes_with_audit(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="k-12345678")
    db.add(KeyRecord(tenant_id=t.id, dashboard_user_id=u.id, ov_user_id="alice",
                     key_kind="user", key_hint="k-123456"))
    db.add(AuditLog(actor_user_id=u.id, actor_name="alice", action="key.view"))
    await db.commit()
    ov_calls["responses"].append((200, {}))
    r = await client.delete(f"/api/v1/users/{u.id}", headers=auth_headers(admin))
    assert r.status_code == 204
    assert (await db.scalars(select(KeyRecord))).all() == []
    log = (await db.scalars(select(AuditLog).where(AuditLog.action == "key.view"))).one()
    assert log.actor_user_id is None and log.actor_name == "alice"
    actions = [a.action for a in (await db.scalars(select(AuditLog))).all()]
    assert "user.delete" in actions


async def test_delete_guardrails(client, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")  # admin_user_id 默认 "boss"
    initial = await make_user("bosslogin", "Passw0rd!", "team_admin",
                               tenant=t, ov_user_id="boss")
    plain = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    platform = await make_user("root2", "Admin#12345", "admin")

    def delete(uid, actor):
        return client.delete(f"/api/v1/users/{uid}", headers=auth_headers(actor))

    assert (await delete(admin.id, admin)).status_code == 400      # 不能删自己
    assert (await delete(platform.id, admin)).status_code == 403   # 平台管理员账号
    assert (await delete(initial.id, admin)).status_code == 409    # 账户初始管理员

    # 团队最后一个 team_admin：该团队本地仅此一个 team_admin，且其 ov_user_id 非账户初始管理员
    t2 = await make_tenant("gamma")
    solo = await make_user("soloboss", "Passw0rd!", "team_admin",
                            tenant=t2, ov_user_id="soloboss")
    assert (await delete(solo.id, admin)).status_code == 409

    # team_admin 跨团队删人
    t3 = await make_tenant("beta")
    outsider = await make_user("b1", "Passw0rd!", "user", tenant=t3, ov_user_id="b1")
    assert (await delete(outsider.id, initial)).status_code == 403
    assert ov_calls["calls"] == []

    # team_admin 删本团队普通成员成功（默认 mock 200）
    assert (await delete(plain.id, initial)).status_code == 204


async def test_delete_ov_refused_local_untouched(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    ov_calls["responses"].append((400, {"detail": "last admin"}))
    r = await client.delete(f"/api/v1/users/{u.id}", headers=auth_headers(admin))
    assert r.status_code == 400
    assert await db.get(DashboardUser, u.id) is not None
    assert any(a.action == "user.delete.fail"
               for a in (await db.scalars(select(AuditLog))).all())


# ---------- USER-7 同步 ----------
async def test_sync_user_report(client, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t,
                         ov_user_id="alice", ov_role="user")
    ov_calls["responses"].append((200, {"users": [{"user_id": "alice", "role": "admin"}]}))
    r = await client.post(f"/api/v1/users/{u.id}/sync", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["ov_exists"] is True
    assert body["consistent"] is False
    assert body["ov_role"] == "admin" and body["local_ov_role"] == "user"


async def test_sync_user_missing_remote(client, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    ov_calls["responses"].append((200, {"users": []}))
    r = await client.post(f"/api/v1/users/{u.id}/sync", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["ov_exists"] is False
    assert body["consistent"] is False


# ---------- USER-5 对抗：重签/重置联动不得复活正常停用账号 ----------
async def test_regenerate_does_not_revive_disabled_user_with_key(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                        ov_role="user", ov_key="old-key-1234567", is_active=False)
    ov_calls["responses"].append((200, {"key": "new-key-76543210"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/regenerate-key", json={}, headers=auth_headers(admin)
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "new-key-76543210"
    assert u.is_active is False  # 正常停用账号重签不改变启用位


async def test_team_admin_regenerate_does_not_revive_disabled_member(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t, ov_user_id="boss")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                        ov_role="user", ov_key="old-key-1234567", is_active=False)
    ov_calls["responses"].append((200, {"key": "new-key-76543210"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/regenerate-key", json={}, headers=auth_headers(ta)
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "new-key-76543210"
    assert u.is_active is False  # team_admin 路径同样不复活


async def test_reset_with_rotation_keeps_disabled_user_inactive(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                        ov_role="user", ov_key="old-key-1234567", is_active=False)
    ov_calls["responses"].append((200, {"key": "new-key-76543210"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "New#123456", "regenerate_key": True},
        headers=auth_headers(admin),
    )
    assert r.status_code == 204
    await db.refresh(u)
    assert u.is_active is False
    assert decrypt_secret(u.ov_user_key_encrypted) == "new-key-76543210"
    # 仍停用：即便密码已换，登录被 authenticate 以停用拒绝（401）
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "New#123456"},
    )
    assert login.status_code == 401


async def test_reset_rotation_ov_failure_keeps_password_and_no_audit(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                        ov_role="user", ov_key="old-key-1234567")
    old_hash = u.password_hash
    ov_calls["responses"].append((500, {"detail": "boom"}))
    r = await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "New#123456", "regenerate_key": True},
        headers=auth_headers(admin),
    )
    assert r.status_code == 500
    await db.refresh(u)
    assert u.password_hash == old_hash  # rotate 失败抛在改密之前
    assert (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == "user.password.reset")
        )
    ).all() == []


# ---------- USER-7 同步补测：409 分支与 consistent=True ----------
async def test_sync_platform_admin_target_conflicts(
    client, make_user, auth_headers
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    other = await make_user("root2", "Admin#12345", "admin")
    r = await client.post(
        f"/api/v1/users/{other.id}/sync", headers=auth_headers(admin)
    )
    assert r.status_code == 409


async def test_sync_consistent_when_remote_role_matches(
    client, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t,
                        ov_user_id="alice", ov_role="user")
    ov_calls["responses"].append(
        (200, {"users": [{"user_id": "alice", "role": "user"}]})
    )
    r = await client.post(f"/api/v1/users/{u.id}/sync", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["ov_exists"] is True
    assert body["consistent"] is True
