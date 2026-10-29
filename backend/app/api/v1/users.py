"""用户管理路由：平台 admin 全权，team_admin 限本团队普通成员。"""
from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import CurrentUser, DBSession, OVAdminDep
from app.models import DashboardUser, Tenant
from app.schemas.user import UserCreateRequest, UserOut
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

_MANAGERS = ("admin", "team_admin")


def _to_out(u: DashboardUser) -> UserOut:
    has_key = bool(u.ov_user_key_encrypted)
    return UserOut(
        id=u.id, username=u.username, role=u.role, is_active=u.is_active,
        tenant_id=u.tenant_id,
        account_id=u.tenant.ov_account_id if u.tenant else None,
        ov_user_id=u.ov_user_id, ov_role=u.ov_role,
        has_key=has_key,
        key_state="current" if has_key else "pending",
        key_synced_at=u.key_synced_at,
        must_change_password=u.must_change_password,
        last_login_at=u.last_login_at, created_at=u.created_at,
    )


async def _manager(user: CurrentUser) -> DashboardUser:
    if user.role not in _MANAGERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无用户管理权限")
    return user


@router.get("", response_model=list[UserOut])
async def list_users(
    db: DBSession,
    current: CurrentUser,
    tenant_id: int | None = None,
    keyword: str | None = None,
):
    actor = await _manager(current)
    users = await user_service.list_users(
        db, actor, tenant_id=tenant_id, keyword=keyword
    )
    return [_to_out(u) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    db: DBSession,
    ov: OVAdminDep,
    current: CurrentUser,
):
    actor = await _manager(current)
    ip = request.client.host if request.client else None
    user = await user_service.create_user(db, ov, actor, payload, ip=ip)
    return _to_out(user)
