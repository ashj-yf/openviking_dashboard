"""认证路由：登录、当前用户、改密与注销。"""
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import get_settings, is_env_admin
from app.core.deps import CurrentUser, DBSession
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    TokenResponse,
)
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    db: DBSession,
) -> TokenResponse:
    user = await auth_service.authenticate(db, payload.username, payload.password)
    if user is None:
        # 用户不存在与密码错误返回完全一致的响应，避免账号枚举。
        await audit_service.record(
            db,
            "auth.login.fail",
            actor_name=payload.username,
            detail={"username": payload.username},
            ip=_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    settings = get_settings()
    token = auth_service.issue_token(user)
    await audit_service.record(
        db,
        "auth.login.success",
        actor=user,
        ip=_client_ip(request),
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        role=user.role,
    )


@router.get("/me")
async def me(current_user: CurrentUser) -> MeOut:
    user = current_user
    return MeOut(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        account_id=user.tenant.ov_account_id if user.tenant else None,
        ov_user_id=user.ov_user_id,
        ov_role=user.ov_role,
        has_ov_key=bool(user.ov_user_key_encrypted),
        key_synced_at=user.key_synced_at,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        is_env_admin=is_env_admin(get_settings(), user.username),
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: CurrentUser,
    db: DBSession,
) -> Response:
    try:
        await auth_service.change_password(
            db, current_user, payload.old_password, payload.new_password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await audit_service.record(
        db,
        "auth.password.change",
        actor=current_user,
        ip=_client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: CurrentUser,
    db: DBSession,
) -> Response:
    # 无状态 JWT：服务端不做黑名单，审计留痕后由前端丢弃令牌。
    await audit_service.record(
        db,
        "auth.logout",
        actor=current_user,
        ip=_client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
