import pytest
from jwt import decode as jwt_decode
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import AuditLog, DashboardUser
from app.services import audit_service, auth_service


async def _make_user(db, username="u1", password="Admin#12345", role="user", **kw):
    user = DashboardUser(
        username=username, password_hash=hash_password(password), role=role, **kw
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_authenticate_success_updates_last_login(db):
    await _make_user(db)
    user = await auth_service.authenticate(db, "u1", "Admin#12345")
    assert user is not None and user.last_login_at is not None


async def test_authenticate_failure_returns_none(db):
    await _make_user(db)
    assert await auth_service.authenticate(db, "u1", "wrong") is None
    assert await auth_service.authenticate(db, "ghost", "Admin#12345") is None
    user = await _make_user(db, username="u2", is_active=False)
    assert await auth_service.authenticate(db, "u2", "Admin#12345") is None


async def test_issue_token_claims(db):
    user = await _make_user(db, username="u3", role="team_admin")
    token = auth_service.issue_token(user)
    payload = jwt_decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload == {"sub": str(user.id), "username": "u3", "role": "team_admin",
                       "iat": payload["iat"], "exp": payload["exp"]}


async def test_change_password_rules(db):
    user = await _make_user(db, password="Admin#12345", must_change_password=True)
    with pytest.raises(ValueError, match="旧密码不正确"):
        await auth_service.change_password(db, user, "nope", "NewPass#2026")
    with pytest.raises(ValueError, match="不能与旧密码相同"):
        await auth_service.change_password(db, user, "Admin#12345", "Admin#12345")
    await auth_service.change_password(db, user, "Admin#12345", "NewPass#2026")
    assert user.must_change_password is False
    assert await auth_service.authenticate(db, "u1", "NewPass#2026") is not None


async def test_ensure_first_admin_idempotent(db):
    settings = get_settings()
    await auth_service.ensure_first_admin(db, settings)
    await auth_service.ensure_first_admin(db, settings)
    rows = (await db.scalars(
        select(DashboardUser).where(DashboardUser.role == "admin")
    )).all()
    assert len(rows) == 1
    assert rows[0].username == settings.first_admin_username
    assert rows[0].must_change_password is True


async def test_audit_record_persists_and_never_includes_password(db):
    await audit_service.record(
        db, "auth.login.fail", actor_name="u1",
        detail={"username": "u1"}, ip="127.0.0.1",
    )
    row = (await db.scalars(select(AuditLog))).one()
    assert row.action == "auth.login.fail" and row.ip == "127.0.0.1"
    assert "Admin#12345" not in (row.detail_json or "")


async def test_audit_record_swallows_commit_error(db, monkeypatch):
    async def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(db, "commit", _boom)
    # 不抛异常即通过
    await audit_service.record(db, "auth.logout", actor_name="u1")
