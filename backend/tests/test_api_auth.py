import httpx
import pytest
import pytest_asyncio


async def _login(client, username, password):
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


@pytest_asyncio.fixture
async def admin_headers(client, make_user):
    user = await make_user(username="admin", password="Admin#12345", role="admin")
    resp = await _login(client, "admin", "Admin#12345")
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user


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


async def test_non_admin_cannot_reset_password(client, make_user):
    await make_user(username="carol", password="Admin#12345", role="user")
    token = (await _login(client, "carol", "Admin#12345")).json()["access_token"]
    target = await make_user(username="dave", password="Admin#12345", role="user")
    resp = await client.post(
        f"/api/v1/admin-users/{target.id}/reset-password",
        json={"new_password": "Reset#2026xx"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_admin_reset_password_then_new_password_works(client, admin_headers, make_user):
    headers, admin = admin_headers
    target = await make_user(username="erin", password="OldPass#2026", role="user")
    resp = await client.post(
        f"/api/v1/admin-users/{target.id}/reset-password",
        json={"new_password": "Reset#2026xx"},
        headers=headers,
    )
    assert resp.status_code == 204
    assert (await _login(client, "erin", "OldPass#2026")).status_code == 401
    assert (await _login(client, "erin", "Reset#2026xx")).status_code == 200
    assert (await client.post(f"/api/v1/admin-users/{99999}/reset-password",
            json={"new_password": "Reset#2026xx"}, headers=headers)).status_code == 404


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


async def test_lifespan_creates_tables_and_bootstraps_admin_idempotently():
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
            assert admin.role == "admin" and admin.must_change_password is True
    # 第二次进入 lifespan：不重复创建
    async with app.router.lifespan_context(app):
        async with SessionLocal() as session:
            count = await session.scalar(select(func.count()).select_from(DashboardUser))
            assert count == 1
