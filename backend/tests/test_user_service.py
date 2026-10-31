"""team_admin 范围守卫与开通流程。"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import DashboardUser, KeyRecord
from app.schemas.user import UserCreateRequest
from app.services import user_service
from app.services.openviking.client import OpenVikingError


class _AdminAPI:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def register_user(self, account_id, user_id, *, role="user", seed=None):
        self.calls.append(("register", account_id, user_id, role, seed))
        v = self.responses.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    async def regenerate_key(self, account_id, user_id, *, seed=None):
        self.calls.append(("key", account_id, user_id, seed))
        v = self.responses.pop(0)
        if isinstance(v, Exception):
            raise v
        return v


async def test_guard_matrix(db, make_tenant, make_user):
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    platform = await make_user("rootadmin", "Admin#12345", "admin")
    ta1 = await make_user("boss1", "Passw0rd!", "team_admin", tenant=t1, ov_user_id="boss1")
    ta2 = await make_user("boss2", "Passw0rd!", "team_admin", tenant=t2, ov_user_id="boss2")
    u1 = await make_user("alice", "Passw0rd!", "user", tenant=t1, ov_user_id="alice")

    await user_service.assert_can_manage(platform, u1)  # 不抛
    await user_service.assert_can_manage(ta1, u1)      # 本团队普通成员
    with pytest.raises(HTTPException) as e:
        await user_service.assert_can_manage(ta1, ta2)  # 跨团队
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await user_service.assert_can_manage(ta1, ta1)  # 不能操作 team_admin
    assert e.value.status_code == 403


async def test_create_user_happy_path(db, make_user, make_tenant):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov = _AdminAPI([{"user_id": "carol"}, {"key": "user-key-12345678"}])
    payload = UserCreateRequest(username="carol", password="Carol#1234", tenant_id=t.id)
    user = await user_service.create_user(db, ov, admin, payload, ip=None)
    assert user.is_active is True
    assert user.must_change_password is True
    assert user.ov_user_id == "carol"
    assert user.ov_role == "user"
    assert user.ov_user_key_encrypted is not None
    assert ov.calls[0] == ("register", "acme", "carol", "user", None)
    assert ov.calls[1][0] == "key"
    rec = (await db.scalars(
        select(KeyRecord).where(KeyRecord.dashboard_user_id == user.id)
    )).one()
    assert rec.is_current is True
    assert rec.key_hint == "user-key"[:8]
    assert rec.seed_used is False


async def test_register_response_with_key_skips_second_call(db, make_user, make_tenant):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov = _AdminAPI([{"user_id": "dave", "key": "dave-key-12345678"}])
    payload = UserCreateRequest(username="dave", password="Dave#12345", tenant_id=t.id)
    await user_service.create_user(db, ov, admin, payload, ip=None)
    assert len(ov.calls) == 1  # 注册响应直带 key，免签发调用
    assert ov.calls[0][0] == "register"


async def test_team_admin_forced_to_own_tenant_and_role_user(db, make_user, make_tenant):
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t1, ov_user_id="boss")
    ov = _AdminAPI([{"user_id": "x"}, {"key": "x-key-1234567890"}])
    # 传别的 tenant_id 被强制为本团队；请求开 team_admin 被 403
    payload = UserCreateRequest(
        username="x", password="Xxxx#12345", tenant_id=t2.id, role="team_admin"
    )
    with pytest.raises(HTTPException) as e:
        await user_service.create_user(db, ov, ta, payload, ip=None)
    assert e.value.status_code == 403

    payload2 = UserCreateRequest(username="x", password="Xxxx#12345", tenant_id=t2.id)
    user = await user_service.create_user(db, ov, ta, payload2, ip=None)
    assert user.tenant_id == t1.id
    assert ov.calls[0][1] == "acme"


async def test_duplicate_username_and_ov_user_conflict(db, make_user, make_tenant):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    await make_user("carol", "Carol#1234", "user", tenant=t, ov_user_id="carol")
    ov = _AdminAPI()
    # username 唯一（全局）
    with pytest.raises(HTTPException) as e:
        await user_service.create_user(
            db, ov, admin,
            UserCreateRequest(username="carol", password="Carol#1234", tenant_id=t.id),
            ip=None,
        )
    assert e.value.status_code == 409
    # 同团队 ov_user_id 唯一（username 不同也拦截，且不触达 OV）
    with pytest.raises(HTTPException) as e:
        await user_service.create_user(
            db, ov, admin,
            UserCreateRequest(username="carol2", password="Carol#1234",
                              tenant_id=t.id, ov_user_id="carol"),
            ip=None,
        )
    assert e.value.status_code == 409
    assert ov.calls == []


async def test_admin_must_supply_tenant(db, make_user):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ov = _AdminAPI()
    payload = UserCreateRequest(username="lonely", password="Lonely#1234")
    with pytest.raises(HTTPException) as e:
        await user_service.create_user(db, ov, admin, payload, ip=None)
    assert e.value.status_code == 400


async def test_key_issue_failure_leaves_inactive_half_product(db, make_user, make_tenant):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov = _AdminAPI([
        {"user_id": "erin"},
        OpenVikingError(500, "boom", "/key"),
    ])
    payload = UserCreateRequest(username="erin", password="Erin#12345", tenant_id=t.id)
    with pytest.raises(HTTPException) as e:
        await user_service.create_user(db, ov, admin, payload, ip=None)
    assert e.value.status_code == 502
    row = (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == "erin")
    )).one()
    assert row.is_active is False
    assert row.ov_user_id == "erin"
    assert row.ov_user_key_encrypted is None
    assert (await db.scalars(select(KeyRecord))).all() == []


# ---------- 末位平台管理员（服务层直接构造：API 路径上自我保护先拦截） ----------
async def test_cannot_disable_last_active_platform_admin(db, make_user):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    inactive = await make_user("root2", "Admin#12345", "admin", is_active=False)
    with pytest.raises(HTTPException) as e:
        await user_service.set_enabled(db, inactive, admin, False, ip=None)
    assert e.value.status_code == 409
