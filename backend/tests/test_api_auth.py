from datetime import datetime, timezone

from jwt import decode as jwt_decode
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.models import AuditLog, DashboardUser
from app.services.auth_service import issue_bind_token, issue_token
from conftest import FakeUser


async def _login(client, username, password):
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def _config_payload(**kw) -> dict:
    """ldap-config PUT/test 请求体；各测试按需覆盖字段。"""
    base = {
        "enabled": True,
        "server_host": "ldap.test",
        "server_port": 389,
        "encryption": "none",
        "bind_dn": "cn=svc,dc=test",
        "bind_password": "svc-secret",
        "user_base_dn": "ou=people,dc=test",
        "user_filter": "(uid={username})",
        "attr_uid": "uid",
        "attr_mail": "mail",
        "attr_display_name": "cn",
    }
    base.update(kw)
    return base


async def _make_ldap_bound(db, username: str, ldap_dn: str):
    """直接造一个已绑定 LDAP 的用户（password_hash 置空、四字段齐写）。"""
    user = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == username)
    )).one()
    user.auth_source = "ldap"
    user.ldap_username = username
    user.ldap_dn = ldap_dn
    user.bound_at = datetime.now(timezone.utc)
    user.password_hash = None
    await db.commit()
    return user


async def _audit_count(db, action: str) -> int:
    return (await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
    )) or 0


async def test_login_success_and_same_error_for_bad_credentials(client, make_user, db):
    await make_user(username="alice", password="Admin#12345", role="user")
    ok = await _login(client, "alice", "Admin#12345")
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "bearer" and body["role"] == "user"
    assert body["expires_in"] == 720 * 60

    bad_pw = await _login(client, "alice", "wrong-password")
    no_user = await _login(client, "ghost", "whatever-123")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["detail"] == no_user.json()["detail"] == "用户名或密码错误"


async def test_me_requires_token_and_never_leaks_key(client, make_user, db):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    user = await make_user(
        username="bob", password="Admin#12345", role="team_admin",
        tenant={"ov_account_id": "acme", "admin_user_id": "bob"},
        ov_user_id="bob", ov_role="admin", ov_key="ov-secret-key-value",
    )
    resp = await _login(client, "bob", "Admin#12345")
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {resp.json()['access_token']}"},
    )
    assert me.status_code == 200
    body = me.text
    assert "ov-secret-key-value" not in body
    data = me.json()
    assert data["has_ov_key"] is True and data["account_id"] == "acme"
    assert "ov_user_key_encrypted" not in data


async def test_change_password_flow_and_must_change_unlock(client, make_user):
    await make_user(username="frank", password="Admin#12345", role="user",
                    must_change_password=True)
    token = (await _login(client, "frank", "Admin#12345")).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 强制改密期间 me 仍可用
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    bad = await client.post("/api/v1/auth/change-password",
                            json={"old_password": "nope", "new_password": "NewPass#2026"},
                            headers=headers)
    assert bad.status_code == 400
    ok = await client.post("/api/v1/auth/change-password",
                           json={"old_password": "Admin#12345", "new_password": "NewPass#2026"},
                           headers=headers)
    assert ok.status_code == 204
    assert (await _login(client, "frank", "Admin#12345")).status_code == 401
    assert (await _login(client, "frank", "NewPass#2026")).status_code == 200


async def test_logout_returns_204(client, make_user):
    await make_user(username="gina", password="Admin#12345", role="user")
    token = (await _login(client, "gina", "Admin#12345")).json()["access_token"]
    resp = await client.post("/api/v1/auth/logout",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204  # 无状态：前端丢弃 token，审计留痕


async def test_disabled_user_token_rejected_immediately(client, make_user, db):
    user = await make_user(username="hank", password="Admin#12345", role="user")
    token = (await _login(client, "hank", "Admin#12345")).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    user.is_active = False
    await db.commit()
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_login_audits_and_audit_contains_no_password(client, make_user, db):
    from sqlalchemy import func, select
    from app.models import AuditLog
    await make_user(username="ivy", password="Admin#12345", role="user")
    await _login(client, "ivy", "Admin#12345")
    await _login(client, "ivy", "wrong-password")
    actions = dict((await db.execute(
        select(AuditLog.action, func.count()).group_by(AuditLog.action)
    )).all())
    assert actions.get("auth.login.success") == 1
    assert actions.get("auth.login.fail") == 1
    raw = (await db.execute(select(AuditLog.detail_json))).scalars().all()
    assert all("Admin#12345" not in (d or "") for d in raw)


async def test_lifespan_creates_tables_and_syncs_first_admin_idempotently():
    from sqlalchemy import func, select
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.main import create_app
    from app.models import DashboardUser

    app = create_app()
    async with app.router.lifespan_context(app):
        async with SessionLocal() as session:
            count = await session.scalar(select(func.count()).select_from(DashboardUser))
            assert count == 1
            admin = await session.scalar(
                select(DashboardUser).where(DashboardUser.username == get_settings().first_admin_username)
            )
            assert admin.role == "admin" and admin.is_active is True
            # 超管 UI 禁改密，密码门禁不可置位（否则死锁）
            assert admin.must_change_password is False
    # 第二次进入 lifespan：强制刷新语义下仍不重复创建
    async with app.router.lifespan_context(app):
        async with SessionLocal() as session:
            count = await session.scalar(select(func.count()).select_from(DashboardUser))
            assert count == 1


async def test_env_admin_change_password_rejected_and_me_flag(client, make_user):
    from app.core.config import get_settings
    username = get_settings().first_admin_username
    await make_user(username=username, password="Admin#12345", role="admin")
    token = (await _login(client, username, "Admin#12345")).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["is_env_admin"] is True
    rejected = await client.post("/api/v1/auth/change-password",
                                 json={"old_password": "Admin#12345", "new_password": "NewPass#2026"},
                                 headers=headers)
    assert rejected.status_code == 400
    assert ".env" in rejected.json()["detail"]


async def test_me_flag_false_for_normal_user(client, make_user):
    await make_user(username="nina", password="Admin#12345", role="user")
    token = (await _login(client, "nina", "Admin#12345")).json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200 and me.json()["is_env_admin"] is False


# ---------------------------------------------------------------------------
# LDAP 模式：登录分流、绑定迁移、bind_token 与 ldap-config 管理端点（03 B3）
# ---------------------------------------------------------------------------


async def test_login_must_bind_unbound_user_returns_bind_token(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["mike"] = FakeUser("uid=mike,ou=people,dc=test", "ldap-pw-1", "m@t", "Mike")
    await make_user(username="mike", password="Admin#12345", role="user")
    resp = await _login(client, "mike", "Admin#12345")
    assert resp.status_code == 200
    body = resp.json()
    assert body["must_bind"] is True
    assert body["access_token"] == ""
    assert body["bind_token"]
    # 引导绑定阶段：不更新 last_login、不发正式 token
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "mike")
    )).one()
    assert row.last_login_at is None
    claims = jwt_decode(body["bind_token"], get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["purpose"] == "ldap_bind" and claims["sub"] == str(row.id)


async def test_bind_success_clears_local_password_and_sets_fields(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["mike"] = FakeUser("uid=mike,ou=people,dc=test", "ldap-pw-1", "m@t", "Mike")
    user = await make_user(username="mike", password="Admin#12345", role="user")
    bind_token = (await _login(client, "mike", "Admin#12345")).json()["bind_token"]
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "mike", "ldap_password": "ldap-pw-1"},
        headers={"Authorization": f"Bearer {bind_token}"},
    )
    assert resp.status_code == 204
    row = (await db.scalars(select(DashboardUser).where(DashboardUser.id == user.id))).one()
    assert row.auth_source == "ldap"
    assert row.ldap_username == "mike"
    assert row.ldap_dn == "uid=mike,ou=people,dc=test"
    assert row.bound_at is not None
    assert row.password_hash is None


async def test_bind_wrong_ldap_password_400_inline(client, make_user, db, ldap_cfg, fake_ldap):
    fake_ldap.users["mike"] = FakeUser("uid=mike,ou=people,dc=test", "ldap-pw-1", "m@t", "Mike")
    await make_user(username="mike", password="Admin#12345", role="user")
    bind_token = (await _login(client, "mike", "Admin#12345")).json()["bind_token"]
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "mike", "ldap_password": "nope"},
        headers={"Authorization": f"Bearer {bind_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LDAP 账号或密码错误"
    assert await _audit_count(db, "auth.ldap.bind.fail") == 1
    # 失败不迁移：本地口令仍在、绑定字段未写
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "mike")
    )).one()
    assert row.password_hash is not None and row.auth_source == "local"


async def test_bind_conflict_ldap_username_taken_409(client, make_user, db, ldap_cfg, fake_ldap):
    await make_user(username="nadia", password="Admin#12345", role="user",
                    ldap_username="shared-uid")
    fake_ldap.users["nia"] = FakeUser(
        "uid=shared-uid,ou=people,dc=test", "pw-2", "n2@t", "Nia"
    )
    await make_user(username="nia", password="Admin#12345", role="user")
    bind_token = (await _login(client, "nia", "Admin#12345")).json()["bind_token"]
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "shared-uid", "ldap_password": "pw-2"},
        headers={"Authorization": f"Bearer {bind_token}"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "该 LDAP 账号已被其他用户绑定"
    assert fake_ldap.verify_calls == []  # 占用检查先于 LDAP 验密


async def test_bind_replay_after_success_409(client, make_user, db, ldap_cfg, fake_ldap):
    fake_ldap.users["mike"] = FakeUser("uid=mike,ou=people,dc=test", "ldap-pw-1", "m@t", "Mike")
    await make_user(username="mike", password="Admin#12345", role="user")
    bind_token = (await _login(client, "mike", "Admin#12345")).json()["bind_token"]
    payload = {"ldap_username": "mike", "ldap_password": "ldap-pw-1"}
    headers = {"Authorization": f"Bearer {bind_token}"}
    first = await client.post("/api/v1/auth/ldap/bind", json=payload, headers=headers)
    assert first.status_code == 204
    # 同一 bind_token 重放：账号已是 ldap 来源，返回 409
    replay = await client.post("/api/v1/auth/ldap/bind", json=payload, headers=headers)
    assert replay.status_code == 409
    assert replay.json()["detail"] == "该账号已绑定 LDAP"


async def test_bind_token_rejected_as_session_token(client, make_user):
    """bind_token 不得反向充当会话令牌（AUTH-10）：purpose 非空令牌打受保护接口一律 401。"""
    user = await make_user(username="vera", password="Admin#12345", role="user")
    headers = {"Authorization": f"Bearer {issue_bind_token(user.id)}"}
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "认证令牌无效或已过期"


async def test_bind_token_expired_401(client, make_user, ldap_cfg, fake_ldap):
    fake_ldap.users["mia"] = FakeUser("uid=mia,ou=people,dc=test", "pw-3", "m3@t", "Mia")
    user = await make_user(username="mia", password="Admin#12345", role="user")
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "mia", "ldap_password": "pw-3"},
        headers={"Authorization": f"Bearer {issue_bind_token(user.id, minutes=-1)}"},
    )
    assert resp.status_code == 401


async def test_bind_token_wrong_purpose_401(client, make_user, ldap_cfg, fake_ldap):
    fake_ldap.users["mia"] = FakeUser("uid=mia,ou=people,dc=test", "pw-3", "m3@t", "Mia")
    user = await make_user(username="mia", password="Admin#12345", role="user")
    # 普通登录令牌冒充 bind_token：purpose 不符一律 401
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "mia", "ldap_password": "pw-3"},
        headers={"Authorization": f"Bearer {issue_token(user)}"},
    )
    assert resp.status_code == 401


async def test_ldap_mode_bound_user_login_success_and_last_login_updated(
    client, make_user, db, auth_headers, ldap_cfg, fake_ldap
):
    fake_ldap.users["carla"] = FakeUser("uid=carla,ou=people,dc=test", "ldap-pw-4", "c@t", "Carla")
    await make_user(username="carla", password="Local#12345", role="user")
    await _make_ldap_bound(db, "carla", "uid=carla,ou=people,dc=test")
    resp = await _login(client, "carla", "ldap-pw-4")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["must_bind"] is False and body["role"] == "user"
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "carla")
    )).one()
    assert row.last_login_at is not None
    # 已绑定后本地口令彻底作废（password_hash 为空）
    assert (await _login(client, "carla", "Local#12345")).status_code == 401


async def test_ldap_mode_bound_user_bad_password_401_uniform(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["carla"] = FakeUser("uid=carla,ou=people,dc=test", "ldap-pw-4", "c@t", "Carla")
    await make_user(username="carla", password="Local#12345", role="user")
    await _make_ldap_bound(db, "carla", "uid=carla,ou=people,dc=test")
    resp = await _login(client, "carla", "wrong-ldap-pw")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"


async def test_ldap_down_bound_user_503_explicit_message(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["carla"] = FakeUser("uid=carla,ou=people,dc=test", "ldap-pw-4", "c@t", "Carla")
    await make_user(username="carla", password="Local#12345", role="user")
    await _make_ldap_bound(db, "carla", "uid=carla,ou=people,dc=test")
    fake_ldap.fail_connect = True
    resp = await _login(client, "carla", "ldap-pw-4")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "LDAP 服务不可用，请联系管理员"


async def test_env_admin_bypasses_ldap_when_enabled(client, make_user, ldap_cfg, fake_ldap):
    username = get_settings().first_admin_username  # conftest 固定 "admin"
    fake_ldap.users[username] = FakeUser(
        f"uid={username},ou=people,dc=test", "ldap-admin-pw", "a@t", "Admin"
    )
    await make_user(username=username, password="Admin#12345", role="admin")
    ok = await _login(client, username, "Admin#12345")
    assert ok.status_code == 200
    body = ok.json()
    assert body["access_token"] and body["must_bind"] is False and body["role"] == "admin"
    # 超管恒本地 bcrypt：即便 LDAP 目录存在同名用户也不走 LDAP
    assert (await _login(client, username, "ldap-admin-pw")).status_code == 401
    assert fake_ldap.search_calls == []


async def test_jit_first_login_creates_unprovisioned_user(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["newbie"] = FakeUser("uid=newbie,ou=people,dc=test", "Nw#123456", "n@t", "Newbie")
    resp = await _login(client, "newbie", "Nw#123456")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["must_bind"] is False and body["role"] == "user"
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "newbie")
    )).one()
    assert row.auth_source == "ldap"
    assert row.ldap_username == "newbie"
    assert row.ldap_dn == "uid=newbie,ou=people,dc=test"
    assert row.bound_at is not None
    assert row.is_active is True and row.must_change_password is False
    assert row.tenant_id is None and row.ov_user_id is None
    assert row.last_login_at is not None
    assert await _audit_count(db, "auth.ldap.jit_create") == 1


async def test_jit_username_conflict_with_env_admin_rejected(
    client, make_user, db, ldap_cfg, fake_ldap
):
    username = get_settings().first_admin_username  # "admin" 即超管：JIT 必须拒绝
    fake_ldap.users[username] = FakeUser(
        f"uid={username},ou=people,dc=test", "Admin#12345", "a@t", "Admin"
    )
    resp = await _login(client, username, "Admin#12345")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"
    rows = (await db.scalars(select(DashboardUser))).all()
    assert rows == []  # 未建档
    assert await _audit_count(db, "auth.ldap.jit_rejected") == 1
    detail = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.ldap.jit_rejected")
    )).one()
    assert "env_admin_name_conflict" in (detail.detail_json or "")


async def test_disabled_user_rejected_before_ldap(client, make_user, db, ldap_cfg, fake_ldap):
    await make_user(username="idle", password="Admin#12345", role="user", is_active=False)
    fake_ldap.users["idle"] = FakeUser("uid=idle,ou=people,dc=test", "pw-5", "i@t", "Idle")
    # 即便 LDAP 密码正确，停用账号也先于 LDAP 拦截
    resp = await _login(client, "idle", "pw-5")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"
    assert fake_ldap.verify_calls == []


async def test_local_mode_unbound_user_still_gets_token(client, make_user, fake_ldap):
    # 未配置 ldap_cfg（LDAP 模式未启用）→ 既有行为，即使目录存在同名用户
    fake_ldap.users["oak"] = FakeUser("uid=oak,ou=people,dc=test", "pw-6", "o@t", "Oak")
    await make_user(username="oak", password="Admin#12345", role="user")
    resp = await _login(client, "oak", "Admin#12345")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["must_bind"] is False and body["bind_token"] is None
    assert fake_ldap.search_calls == []


async def test_ldap_mode_unbound_user_wrong_local_password_401(
    client, make_user, db, ldap_cfg, fake_ldap
):
    # 未绑定本地用户在 LDAP 模式下只认本地口令：错误口令 401 且不触 LDAP 验密
    fake_ldap.users["mike"] = FakeUser("uid=mike,ou=people,dc=test", "ldap-pw-1", "m@t", "Mike")
    await make_user(username="mike", password="Admin#12345", role="user")
    resp = await _login(client, "mike", "wrong-local-pw")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"
    assert fake_ldap.verify_calls == []
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "mike")
    )).one()
    assert row.last_login_at is None  # 未签发任何 token、未更 last_login


async def test_bind_rejected_for_env_admin_403(
    client, make_user, db, auth_headers, ldap_cfg, fake_ldap
):
    from app.services.auth_service import issue_bind_token

    username = get_settings().first_admin_username  # "admin" 即超管
    admin = await make_user(username=username, password="Admin#12345", role="admin")
    fake_ldap.users[username] = FakeUser(
        f"uid={username},ou=people,dc=test", "ldap-admin-pw", "a@t", "Admin"
    )
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": username, "ldap_password": "ldap-admin-pw"},
        headers={"Authorization": f"Bearer {issue_bind_token(admin.id)}"},
    )
    assert resp.status_code == 403
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == username)
    )).one()
    assert row.auth_source == "local" and row.password_hash is not None


async def test_bind_ldap_down_503_no_bind_fail_audit(
    client, make_user, db, ldap_cfg, fake_ldap
):
    fake_ldap.users["mia"] = FakeUser("uid=mia,ou=people,dc=test", "pw-3", "m3@t", "Mia")
    await make_user(username="mia", password="Admin#12345", role="user")
    bind_token = (await _login(client, "mia", "Admin#12345")).json()["bind_token"]
    fake_ldap.fail_connect = True
    resp = await client.post(
        "/api/v1/auth/ldap/bind",
        json={"ldap_username": "mia", "ldap_password": "pw-3"},
        headers={"Authorization": f"Bearer {bind_token}"},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "LDAP 服务不可用，请联系管理员"
    # 服务不可用不是凭据错误：不记 bind.fail
    assert await _audit_count(db, "auth.ldap.bind.fail") == 0


async def test_change_password_rejected_for_ldap_user(
    client, make_user, db, auth_headers, ldap_cfg, fake_ldap
):
    await make_user(username="peter", password="Local#12345", role="user")
    user = await _make_ldap_bound(db, "peter", "uid=peter,ou=people,dc=test")
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "whatever", "new_password": "NewPass#2026"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "LDAP 用户密码由 LDAP 统一管理，无法在此修改"


async def test_me_reports_auth_source_and_ldap_flags(
    client, make_user, db, auth_headers, ldap_cfg, fake_ldap
):
    await make_user(username="peter", password="Local#12345", role="user")
    bound = await _make_ldap_bound(db, "peter", "uid=peter,ou=people,dc=test")
    local = await make_user(username="quinn", password="Admin#12345", role="user")

    me_bound = await client.get("/api/v1/auth/me", headers=auth_headers(bound))
    assert me_bound.status_code == 200
    data = me_bound.json()
    assert data["auth_source"] == "ldap"
    assert data["ldap_bound"] is True and data["ldap_enabled"] is True

    me_local = await client.get("/api/v1/auth/me", headers=auth_headers(local))
    data = me_local.json()
    assert data["auth_source"] == "local"
    assert data["ldap_bound"] is False and data["ldap_enabled"] is True


async def test_ldap_config_requires_admin(client, make_user, auth_headers):
    team_admin = await make_user(username="tadmin", password="Admin#12345", role="team_admin")
    pleb = await make_user(username="pleb", password="Admin#12345", role="user")
    for user in (team_admin, pleb):
        headers = auth_headers(user)
        assert (await client.get("/api/v1/auth/ldap-config", headers=headers)).status_code == 403
        put = await client.put(
            "/api/v1/auth/ldap-config", json=_config_payload(), headers=headers
        )
        assert put.status_code == 403
        test = await client.post(
            "/api/v1/auth/ldap-config/test", json=_config_payload(), headers=headers
        )
        assert test.status_code == 403


async def test_ldap_config_put_never_echoes_password(
    client, make_user, db, auth_headers
):
    admin = await make_user(username="chief", password="Admin#12345", role="admin")
    headers = auth_headers(admin)
    resp = await client.put(
        "/api/v1/auth/ldap-config", json=_config_payload(), headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "bind_password" not in body
    assert "bind_password_enc" not in body
    assert body["has_bind_password"] is True
    assert await _audit_count(db, "ldap.config.update") == 1


async def test_ldap_config_put_omitted_password_keeps_old(
    client, make_user, db, auth_headers
):
    from app.core.crypto import decrypt_secret
    from app.models import LdapConfig

    admin = await make_user(username="chief", password="Admin#12345", role="admin")
    headers = auth_headers(admin)
    first = await client.put(
        "/api/v1/auth/ldap-config", json=_config_payload(), headers=headers
    )
    assert first.status_code == 200
    # 再次保存但省略 bind_password：旧密文保留
    second = await client.put(
        "/api/v1/auth/ldap-config",
        json=_config_payload(server_host="ldap2.test", bind_password=None),
        headers=headers,
    )
    assert second.status_code == 200
    body = second.json()
    assert body["server_host"] == "ldap2.test" and body["has_bind_password"] is True
    row = (await db.scalars(select(LdapConfig))).one()
    assert decrypt_secret(row.bind_password_enc) == "svc-secret"


async def test_ldap_config_test_endpoint_returns_result(
    client, make_user, db, auth_headers, fake_ldap
):
    admin = await make_user(username="chief", password="Admin#12345", role="admin")
    headers = auth_headers(admin)
    fake_ldap.users["smoke-probe"] = FakeUser(
        "uid=smoke-probe,ou=people,dc=test", "probe-pw", "s@t", "Smoke"
    )
    resp = await client.post(
        "/api/v1/auth/ldap-config/test", json=_config_payload(), headers=headers
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "stage": "ok",
        "message": "连接、绑定与用户搜索均正常",
    }
    assert await _audit_count(db, "ldap.config.test") == 1
    # 连接失败：结果体给出阶段与分类文案，HTTP 仍 200
    fake_ldap.fail_connect = True
    failed = await client.post(
        "/api/v1/auth/ldap-config/test", json=_config_payload(), headers=headers
    )
    assert failed.status_code == 200
    assert failed.json()["ok"] is False and failed.json()["stage"] == "connect"
    assert failed.json()["message"] == "LDAP 服务不可用，请联系管理员"
