import pytest
from jwt import decode as jwt_decode
from sqlalchemy import select

from app.core.config import ConfigError, Settings, get_settings
from app.core.security import hash_password
from app.models import AuditLog, DashboardUser
from app.services import audit_service, auth_service


def _sync_settings(username="rootadmin", password="Sync#12345"):
    """构造局部 Settings 实例；初始化参数优先于环境变量。"""
    return Settings(first_admin_username=username, first_admin_password=password)


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


async def test_sync_first_admin_creates_when_missing(db):
    await auth_service.sync_first_admin(db, _sync_settings())
    user = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "rootadmin")
    )).one()
    assert user.role == "admin" and user.is_active is True
    # UI 禁改超管密码：must_change_password 恒 False，避免密码门禁死锁
    assert user.must_change_password is False
    assert await auth_service.authenticate(db, "rootadmin", "Sync#12345") is not None


async def test_sync_first_admin_force_refreshes_existing(db):
    """库中同名账号被降级、停用、密码已改：重启同步必须强制校准并刷新。"""
    await _make_user(db, username="rootadmin", password="Stale#12345",
                     role="user", is_active=False)
    await auth_service.sync_first_admin(db, _sync_settings())
    user = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "rootadmin")
    )).one()
    assert user.role == "admin" and user.is_active is True
    assert user.must_change_password is False
    assert await auth_service.authenticate(db, "rootadmin", "Sync#12345") is not None
    assert await auth_service.authenticate(db, "rootadmin", "Stale#12345") is None


async def test_sync_first_admin_idempotent(db):
    settings = _sync_settings()
    await auth_service.sync_first_admin(db, settings)
    await auth_service.sync_first_admin(db, settings)
    rows = (await db.scalars(
        select(DashboardUser).where(DashboardUser.role == "admin")
    )).all()
    assert len(rows) == 1 and rows[0].username == "rootadmin"


async def test_sync_first_admin_noop_when_env_absent(db):
    """env 未配置时按数据库认证：库中有可用 admin 即放行且不动库。"""
    await _make_user(db, username="keeper", password="Admin#12345", role="admin")
    await auth_service.sync_first_admin(db, _sync_settings(username="", password=""))
    rows = (await db.scalars(select(DashboardUser))).all()
    assert len(rows) == 1 and rows[0].username == "keeper"


async def test_sync_first_admin_rejects_when_no_active_admin(db):
    """env 未配置且库中无可用（启用的）admin：拒绝启动。"""
    with pytest.raises(ConfigError, match="FIRST_ADMIN"):
        await auth_service.sync_first_admin(db, _sync_settings(username="", password=""))
    await _make_user(db, username="ghost", password="Admin#12345",
                     role="admin", is_active=False)
    with pytest.raises(ConfigError):
        await auth_service.sync_first_admin(db, _sync_settings(username="", password=""))


async def test_change_password_rejected_for_env_admin(db):
    """超管账号 UI 禁改密：自助改密一律拒绝，密码仅可经 .env 轮换。"""
    username = get_settings().first_admin_username
    await _make_user(db, username=username, password="Admin#12345", role="admin")
    user = await auth_service.authenticate(db, username, "Admin#12345")
    assert user is not None
    with pytest.raises(ValueError, match=r"\.env"):
        await auth_service.change_password(db, user, "Admin#12345", "NewPass#2026")


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
