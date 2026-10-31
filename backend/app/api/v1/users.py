"""用户管理路由：平台 admin 全权，team_admin 限本团队普通成员。"""
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.deps import AdminUser, CurrentUser, DBSession, OVAdminDep
from app.models import DashboardUser
from app.schemas.user import (
    KeyRegenerateRequest,
    UserCreateRequest,
    UserOut,
    UserResetPasswordRequest,
    UserRoleRequest,
    UserSyncReport,
)
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


@router.patch("/{user_id}/role", response_model=UserOut)
async def set_user_role(
    user_id: int, payload: UserRoleRequest, request: Request,
    db: DBSession, ov: OVAdminDep, admin: AdminUser,
):
    target = await user_service.get_target_or_404(db, user_id)
    ip = request.client.host if request.client else None
    await user_service.set_role(db, ov, admin, target, payload.role, ip=ip)
    return _to_out(target)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: int, payload: UserResetPasswordRequest, request: Request,
    db: DBSession, ov: OVAdminDep, current: CurrentUser,
):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    if actor.role != "admin":
        await user_service.assert_can_manage(actor, target)
    ip = request.client.host if request.client else None
    await user_service.reset_target_password(
        db, ov, actor, target, payload.new_password,
        regenerate=payload.regenerate_key, seed=payload.seed, ip=ip,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_user(user_id: int, request: Request, db: DBSession, current: CurrentUser):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    await user_service.assert_can_manage(actor, target)
    ip = request.client.host if request.client else None
    await user_service.set_enabled(db, actor, target, False, ip=ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_user(user_id: int, request: Request, db: DBSession, current: CurrentUser):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    await user_service.assert_can_manage(actor, target)
    ip = request.client.host if request.client else None
    await user_service.set_enabled(db, actor, target, True, ip=ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/regenerate-key", response_model=UserOut)
async def regenerate_user_key(
    user_id: int, payload: KeyRegenerateRequest, request: Request,
    db: DBSession, ov: OVAdminDep, current: CurrentUser,
):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    await user_service.assert_can_manage(actor, target)
    ip = request.client.host if request.client else None
    await user_service.rotate_user_key(db, ov, actor, target, seed=payload.seed, ip=ip)
    return _to_out(target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int, request: Request, db: DBSession, ov: OVAdminDep, current: CurrentUser
):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    await user_service.assert_can_manage(actor, target)
    ip = request.client.host if request.client else None
    await user_service.delete_user(db, ov, actor, target, ip=ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/sync", response_model=UserSyncReport)
async def sync_user(user_id: int, db: DBSession, ov: OVAdminDep, current: CurrentUser):
    actor = await _manager(current)
    target = await user_service.get_target_or_404(db, user_id)
    await user_service.assert_can_manage(actor, target)
    return await user_service.sync_user(db, ov, target)
