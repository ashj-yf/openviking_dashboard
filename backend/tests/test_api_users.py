"""用户开通、列表与生命周期管理路由。"""
import json
from datetime import datetime, timezone

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


# ---------- 团队可选：无团队落可登录未开通本地账号 ----------
async def test_create_user_without_tenant_creates_unprovisioned(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    r = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "Dave#12345"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tenant_id"] is None
    assert body["ov_user_id"] is None
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert body["key_state"] == "pending"
    u = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "dave")
    )).one()
    assert u.password_hash  # 可登录：本机口令已落
    assert u.ov_user_key_encrypted is None
    assert u.must_change_password is True
    logs = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "user.create").order_by(AuditLog.id)
    )).all()
    assert json.loads(logs[-1].detail_json)["unprovisioned"] is True
    assert ov_calls["calls"] == []  # 全程不触 OV


async def test_create_user_team_admin_without_tenant_400(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    r = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "Dave#12345", "role": "team_admin"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "未选择团队时角色只能为普通用户"
    rows = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "dave")
    )).all()
    assert rows == []  # 本地零写入
    assert ov_calls["calls"] == []


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


# ---------------------------------------------------------------------------
# 超管账号 UI 保护（01 AUTH-3：env 同步的超管在界面中不可修改）
# ---------------------------------------------------------------------------


async def _make_env_admin(make_user):
    from app.core.config import get_settings
    return await make_user(
        get_settings().first_admin_username, "Admin#12345", "admin"
    )


async def test_env_admin_protected_from_all_user_management(
    client, make_user, auth_headers
):
    chief = await make_user("chief", "Admin#12345", "admin")
    env_admin = await _make_env_admin(make_user)
    headers = auth_headers(chief)
    uid = env_admin.id
    role = await client.patch(f"/api/v1/users/{uid}/role",
                              json={"role": "user"}, headers=headers)
    reset = await client.post(f"/api/v1/users/{uid}/reset-password",
                              json={"new_password": "NewPass#2026"}, headers=headers)
    disable = await client.post(f"/api/v1/users/{uid}/disable", headers=headers)
    enable = await client.post(f"/api/v1/users/{uid}/enable", headers=headers)
    rotate = await client.post(f"/api/v1/users/{uid}/regenerate-key",
                               json={}, headers=headers)
    delete = await client.delete(f"/api/v1/users/{uid}", headers=headers)
    sync = await client.post(f"/api/v1/users/{uid}/sync", headers=headers)
    for name, resp in (("role", role), ("reset", reset), ("disable", disable),
                       ("enable", enable), ("rotate", rotate),
                       ("delete", delete), ("sync", sync)):
        assert resp.status_code == 403, f"{name}: {resp.status_code} {resp.text}"
        assert "超管" in resp.json()["detail"]


async def test_cannot_create_user_with_env_admin_username(client, make_user, auth_headers):
    from app.core.config import get_settings
    chief = await make_user("chief", "Admin#12345", "admin")
    r = await client.post("/api/v1/users",
                          json={"username": get_settings().first_admin_username,
                                "password": "Xxxx#12345"},
                          headers=auth_headers(chief))
    assert r.status_code == 400, r.text
    assert "超管" in r.json()["detail"]


async def test_users_list_marks_env_admin(client, make_user, auth_headers):
    from app.core.config import get_settings
    chief = await make_user("chief", "Admin#12345", "admin")
    await _make_env_admin(make_user)
    r = await client.get("/api/v1/users", headers=auth_headers(chief))
    assert r.status_code == 200
    flagged = {u["username"]: u["is_env_admin"] for u in r.json()}
    assert flagged[get_settings().first_admin_username] is True
    assert flagged["chief"] is False


# ---------------------------------------------------------------------------
# B4 LDAP 语义：创建封锁、JIT 开通与守卫
# ---------------------------------------------------------------------------


async def _make_jit_user(db, username: str) -> DashboardUser:
    """构造 LDAP JIT 建档用户（字段与 auth_service 登录分流建档一致）。"""
    user = DashboardUser(
        username=username,
        password_hash=None,
        role="user",
        auth_source="ldap",
        ldap_username=username,
        ldap_dn=f"uid={username},ou=people,dc=test",
        bound_at=datetime.now(timezone.utc),
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_create_user_blocked_in_ldap_mode(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    r = await client.post(
        "/api/v1/users",
        json={"username": "carol", "password": "Carol#1234", "tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "LDAP 模式下禁止创建用户，新用户请直接 LDAP 登录自动建档"
    assert ov_calls["calls"] == []  # 守卫在触达 OV 之前
    rows = (
        await db.scalars(select(DashboardUser).where(DashboardUser.username == "carol"))
    ).all()
    assert rows == []  # 本地零写入


async def test_provision_jit_user_success(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    jit = await _make_jit_user(db, "zhangsan")
    ov_calls["responses"].extend([
        (200, {"user_id": "zhangsan"}),
        (200, {"key": "prov-key-12345678"}),
    ])
    r = await client.post(
        f"/api/v1/users/{jit.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == t.id
    assert body["ov_user_id"] == "zhangsan"
    assert body["ov_role"] == "user"
    assert body["auth_source"] == "ldap"
    assert body["must_change_password"] is False
    assert body["key_state"] == "current"
    assert "prov-key-12345678" not in r.text  # 明文 key 不出接口
    # OV 顺序：先注册后签发
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users"
    assert ov_calls["calls"][0]["body"] == {"user_id": "zhangsan", "role": "user"}
    assert ov_calls["calls"][1]["path"] == "/api/v1/admin/accounts/acme/users/zhangsan/key"
    # 行更新
    await db.refresh(jit)
    assert jit.tenant_id == t.id
    assert jit.ov_user_id == "zhangsan"
    assert jit.ov_role == "user"
    assert jit.role == "user"
    assert jit.must_change_password is False
    # key_records 有行
    rec = (
        await db.scalars(select(KeyRecord).where(KeyRecord.dashboard_user_id == jit.id))
    ).one()
    assert rec.is_current is True
    assert rec.key_hint == "prov-key"[:8]
    # 审计 user.provision
    log = (await db.scalars(select(AuditLog).where(AuditLog.action == "user.provision"))).one()
    assert log.actor_user_id == chief.id
    assert json.loads(log.detail_json) == {
        "tenant": "acme", "ov_user_id": "zhangsan",
        "role": "user", "seed_used": False,
    }


async def test_provision_already_provisioned_409(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    # 有团队的 local 用户已开通（开通已泛化，无团队 local 才可开通）
    local_u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    r1 = await client.post(
        f"/api/v1/users/{local_u.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r1.status_code == 409
    assert r1.json()["detail"] == "该用户已开通"
    # 已开通的 LDAP 用户（tenant 非空）同样拒绝
    prov = await make_user(
        "wangwu", "Passw0rd!", "user", tenant=t, ov_user_id="wangwu",
        auth_source="ldap", ldap_username="wangwu",
        ldap_dn="uid=wangwu,ou=people,dc=test", bound_at=datetime.now(timezone.utc),
    )
    r2 = await client.post(
        f"/api/v1/users/{prov.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "该用户已开通"
    assert ov_calls["calls"] == []


async def test_provision_unknown_tenant_404(
    client, db, make_user, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    jit = await _make_jit_user(db, "zhangsan")
    r = await client.post(
        f"/api/v1/users/{jit.id}/provision",
        json={"tenant_id": 99999},
        headers=auth_headers(chief),
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "团队不存在"
    assert ov_calls["calls"] == []


async def test_provision_ov_failure_local_untouched_502(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    jit = await _make_jit_user(db, "zhangsan")
    ov_calls["responses"].append((502, {"detail": "boom"}))
    r = await client.post(
        f"/api/v1/users/{jit.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 502
    await db.refresh(jit)
    assert jit.tenant_id is None  # 本地零写入
    assert jit.ov_user_id is None
    assert jit.must_change_password is False
    assert (await db.scalars(select(KeyRecord))).all() == []
    provisioned_logs = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "user.provision"))
    ).all()
    assert provisioned_logs == []


async def test_provision_requires_platform_admin(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg
):
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t, ov_user_id="boss")
    jit = await _make_jit_user(db, "zhangsan")
    r = await client.post(
        f"/api/v1/users/{jit.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(ta),
    )
    assert r.status_code == 403, r.text


async def test_provision_key_issue_failed_persists_half_product(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    jit = await _make_jit_user(db, "zhangsan")
    ov_calls["responses"].extend([
        (200, {"user_id": "zhangsan"}),  # 注册成功
        (500, {"detail": "boom"}),       # 补签失败 → _provision_failed 502
    ])
    r = await client.post(
        f"/api/v1/users/{jit.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 502
    body = r.json()["detail"]
    assert body["user_id"] == jit.id
    assert body["ov_user_id"] == "zhangsan"
    # 半成品落库：OV 归属保留，停用且无密文（对齐 create_user 半成品不变量）
    await db.refresh(jit)
    assert jit.tenant_id == t.id
    assert jit.ov_user_id == "zhangsan"
    assert jit.ov_role == "user"
    assert jit.must_change_password is False
    assert jit.is_active is False
    assert jit.ov_user_key_encrypted is None
    # 无 user.provision 审计；issue_failed 审计 detail 含 ov_user_id
    provision_logs = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "user.provision"))
    ).all()
    assert provision_logs == []
    fail_log = (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == "user.key.issue_failed")
        )
    ).one()
    assert json.loads(fail_log.detail_json) == {"ov_user_id": "zhangsan"}
    # 既有复活机制：admin 重签 key 即复活半成品（无密文 → is_active=True + 签发）
    ov_calls["responses"].append((200, {"key": "revive-key-123456"}))
    r2 = await client.post(
        f"/api/v1/users/{jit.id}/regenerate-key", json={}, headers=auth_headers(chief)
    )
    assert r2.status_code == 200, r2.text
    await db.refresh(jit)
    assert jit.is_active is True
    assert jit.ov_user_key_encrypted is not None


async def test_reset_password_blocked_for_ldap_user(
    client, db, make_user, auth_headers, ldap_cfg
):
    chief = await make_user("chief", "Admin#12345", "admin")
    jit = await _make_jit_user(db, "zhangsan")
    r = await client.post(
        f"/api/v1/users/{jit.id}/reset-password",
        json={"new_password": "New#123456"},
        headers=auth_headers(chief),
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "LDAP 用户密码由 LDAP 统一管理，无法重置"
    await db.refresh(jit)
    assert jit.password_hash is None  # 本地口令未被改写
    reset_logs = (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == "user.password.reset")
        )
    ).all()
    assert reset_logs == []


async def test_set_role_blocked_for_unprovisioned_jit(
    client, db, make_user, make_tenant, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    await make_tenant("acme")
    jit = await _make_jit_user(db, "zhangsan")
    r = await client.patch(
        f"/api/v1/users/{jit.id}/role",
        json={"role": "team_admin"},
        headers=auth_headers(chief),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "该用户尚未开通，请先执行开通操作"
    assert ov_calls["calls"] == []
    await db.refresh(jit)
    assert jit.role == "user"


# ---------- 团队可选：本地未开通用户的开通与守卫 ----------
async def test_provision_local_unprovisioned_user_success(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    r0 = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "Dave#12345"},
        headers=auth_headers(chief),
    )
    assert r0.status_code == 201, r0.text
    dave_id = r0.json()["id"]
    ov_calls["responses"].extend([
        (200, {"user_id": "dave"}),
        (200, {"key": "prov-key-12345678"}),
    ])
    r = await client.post(
        f"/api/v1/users/{dave_id}/provision",
        json={"tenant_id": t.id, "role": "user"},
        headers=auth_headers(chief),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == t.id
    assert body["ov_user_id"] == "dave"  # 未显式指定时取登录名
    assert body["has_key"] is True
    assert body["is_active"] is True
    assert body["key_state"] == "current"
    assert body["auth_source"] == "local"
    # local 用户保留创建时的首登改密语义（LDAP JIT 才置 False）
    assert body["must_change_password"] is True
    # OV 顺序：先注册后签发（沿用 JIT 开通 mock 形状）
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users"
    assert ov_calls["calls"][0]["body"] == {"user_id": "dave", "role": "user"}
    assert ov_calls["calls"][1]["path"] == "/api/v1/admin/accounts/acme/users/dave/key"
    u = (await db.scalars(
        select(DashboardUser).where(DashboardUser.id == dave_id)
    )).one()
    assert u.tenant_id == t.id
    assert u.ov_user_id == "dave"
    assert u.ov_role == "user"
    assert u.is_active is True
    assert u.must_change_password is True
    assert u.ov_user_key_encrypted is not None
    log = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "user.provision")
    )).one()
    assert log.actor_user_id == chief.id
    assert json.loads(log.detail_json) == {
        "tenant": "acme", "ov_user_id": "dave",
        "role": "user", "seed_used": False,
    }


async def test_provision_local_already_provisioned_409(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    # 有团队的 local 用户已开通，重复开通拒绝
    local_u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    r = await client.post(
        f"/api/v1/users/{local_u.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "该用户已开通"
    assert ov_calls["calls"] == []  # 守卫在触达 OV 之前


async def test_provision_env_admin_403(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    """env 超管受 AUTH-3 UI 保护：开通不得成为漏网的目标变更入口。"""
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    env_admin = await _make_env_admin(make_user)
    r = await client.post(
        f"/api/v1/users/{env_admin.id}/provision",
        json={"tenant_id": t.id},
        headers=auth_headers(chief),
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "超管账号受环境配置保护，无法在界面修改"
    assert ov_calls["calls"] == []
    await db.refresh(env_admin)
    assert env_admin.tenant_id is None
    assert env_admin.ov_user_id is None
    assert env_admin.role == "admin"


async def test_set_role_local_unprovisioned_409(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    await make_tenant("acme")
    r0 = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "Dave#12345"},
        headers=auth_headers(chief),
    )
    assert r0.status_code == 201, r0.text
    r = await client.patch(
        f"/api/v1/users/{r0.json()['id']}/role",
        json={"role": "team_admin"},
        headers=auth_headers(chief),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "该用户尚未开通，请先执行开通操作"
    assert ov_calls["calls"] == []
    u = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "dave")
    )).one()
    assert u.role == "user"  # 本地角色不变


async def test_regenerate_own_key_unprovisioned_409(
    client, db, make_user, auth_headers, ov_calls
):
    """锁定 rotate_user_key 既有守卫：未开通用户无 OV 身份，自助重签 409。

    未开通用户首登改密前会被初始密码门禁 403 拦截（deps.assert_password_current），
    这里翻掉 must_change_password 模拟已过首登改密的未开通用户，直达目标守卫。
    """
    chief = await make_user("chief", "Admin#12345", "admin")
    r0 = await client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "Dave#12345"},
        headers=auth_headers(chief),
    )
    assert r0.status_code == 201, r0.text
    dave = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "dave")
    )).one()
    dave.must_change_password = False
    await db.commit()
    r = await client.post(
        "/api/v1/credentials/regenerate", json={}, headers=auth_headers(dave)
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "该账号没有 OpenViking 身份"
    assert ov_calls["calls"] == []
    await db.refresh(dave)
    assert dave.ov_user_key_encrypted is None  # 本地密文未变


async def test_delete_jit_user_local_only(
    client, db, make_user, auth_headers, ldap_cfg, ov_calls
):
    chief = await make_user("chief", "Admin#12345", "admin")
    jit = await _make_jit_user(db, "lisi")
    r = await client.delete(f"/api/v1/users/{jit.id}", headers=auth_headers(chief))
    assert r.status_code == 204, r.text
    assert ov_calls["calls"] == []  # 无 OV 身份，不触 OV 删除
    rows = (
        await db.scalars(select(DashboardUser).where(DashboardUser.id == jit.id))
    ).all()
    assert rows == []  # 本地硬删（select 走 populate_existing，读到的非缓存副本）
    delete_logs = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "user.delete"))
    ).all()
    assert len(delete_logs) == 1
    assert delete_logs[0].target_id == str(jit.id)


async def test_user_out_exposes_auth_source(
    client, db, make_user, make_tenant, auth_headers
):
    chief = await make_user("chief", "Admin#12345", "admin")
    t = await make_tenant("acme")
    await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    await _make_jit_user(db, "zhaoliu")
    r = await client.get("/api/v1/users", headers=auth_headers(chief))
    assert r.status_code == 200
    sources = {u["username"]: u["auth_source"] for u in r.json()}
    assert sources["alice"] == "local"
    assert sources["zhaoliu"] == "ldap"
