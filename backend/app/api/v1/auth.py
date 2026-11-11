"""认证路由：登录、当前用户、改密、注销与 LDAP 绑定/配置管理。"""
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.config import get_settings, is_env_admin
from app.core.deps import AdminUser, CurrentUser, DBSession
from app.models import DashboardUser, LdapConfig
from app.schemas.auth import (
    ChangePasswordRequest,
    LdapBindRequest,
    LoginRequest,
    LoginResponse,
    MeOut,
)
from app.schemas.ldap import LdapConfigOut, LdapConfigUpdate, LdapTestResult
from app.services import audit_service, auth_service, ldap_service
from app.services.ldap_service import ldap_mode_enabled

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    db: DBSession,
) -> LoginResponse:
    # 分流编排与审计在 auth_service.login，路由只做 HTTP 映射
    return await auth_service.login(
        db, get_settings(), payload.username, payload.password, ip=_client_ip(request)
    )


@router.get("/me")
async def me(current_user: CurrentUser, db: DBSession) -> MeOut:
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
        auth_source=user.auth_source,
        ldap_bound=user.auth_source == "ldap",
        ldap_enabled=await ldap_mode_enabled(db),
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


# ---------------------------------------------------------------------------
# LDAP 绑定与配置管理
# ---------------------------------------------------------------------------

_bind_bearer = HTTPBearer(auto_error=False)


async def _bind_token_user(
    db: DBSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bind_bearer)
    ] = None,
) -> DashboardUser:
    """bind_token 专用依赖：解码 → 查用户；过期/用途不符/用户不可用一律 401。"""
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = auth_service.decode_bind_token(credentials.credentials)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "绑定令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = (
        await db.scalars(select(DashboardUser).where(DashboardUser.id == user_id))
    ).first()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已禁用")
    return user


@router.post("/ldap/bind", status_code=status.HTTP_204_NO_CONTENT)
async def ldap_bind(
    payload: LdapBindRequest,
    request: Request,
    user: Annotated[DashboardUser, Depends(_bind_token_user)],
    db: DBSession,
) -> Response:
    await auth_service.bind_ldap(
        db,
        get_settings(),
        user,
        payload.ldap_username,
        payload.ldap_password,
        ip=_client_ip(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _config_out(row: LdapConfig | None) -> LdapConfigOut:
    """ORM 行 → 响应：永不回显 bind 密码；从未保存过时给默认空白配置。"""
    if row is None:
        return LdapConfigOut(
            enabled=False,
            server_host="",
            server_port=389,
            encryption="none",
            bind_dn=None,
            user_base_dn="",
            user_filter="(uid={username})",
            attr_uid="uid",
            attr_mail="mail",
            attr_display_name="cn",
            has_bind_password=False,
            updated_at=None,
        )
    return LdapConfigOut(
        enabled=row.enabled,
        server_host=row.server_host,
        server_port=row.server_port,
        encryption=row.encryption,
        bind_dn=row.bind_dn or None,
        user_base_dn=row.user_base_dn,
        user_filter=row.user_filter,
        attr_uid=row.attr_uid,
        attr_mail=row.attr_mail,
        attr_display_name=row.attr_display_name,
        has_bind_password=bool(row.bind_password_enc),
        updated_at=row.updated_at,
    )


@router.get("/ldap-config", response_model=LdapConfigOut)
async def get_ldap_config(_: AdminUser, db: DBSession) -> LdapConfigOut:
    return _config_out(await ldap_service.load_ldap_config(db))


@router.put("/ldap-config", response_model=LdapConfigOut)
async def update_ldap_config(
    payload: LdapConfigUpdate,
    request: Request,
    admin: AdminUser,
    db: DBSession,
) -> LdapConfigOut:
    row = await ldap_service.upsert_ldap_config(db, payload, admin)
    await audit_service.record(
        db,
        "ldap.config.update",
        actor=admin,
        ip=_client_ip(request),
    )
    return _config_out(row)


@router.post("/ldap-config/test", response_model=LdapTestResult)
async def test_ldap_config(
    payload: LdapConfigUpdate,
    request: Request,
    admin: AdminUser,
    db: DBSession,
) -> LdapTestResult:
    result = await ldap_service.test_ldap_config(payload)
    await audit_service.record(
        db,
        "ldap.config.test",
        actor=admin,
        detail={"ok": result.ok, "stage": result.stage},
        ip=_client_ip(request),
    )
    return result
