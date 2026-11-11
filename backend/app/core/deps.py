"""FastAPI 依赖：数据库会话、root key OV 客户端、JWT 鉴权与三角色 RBAC。"""
from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import DashboardUser
from app.services.openviking.admin import OVAdminAPI
from app.services.openviking.client import OVClient, OpenVikingError, root_client
from app.services.openviking.system import OVSystemAPI

DBSession = Annotated[AsyncSession, Depends(get_session)]


async def _root_ov() -> AsyncGenerator[OVClient, None]:
    try:
        client = root_client()
    except OpenVikingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    yield client
    await client.aclose()


RootOVClient = Annotated[OVClient, Depends(_root_ov)]


def ov_system_api(client: RootOVClient) -> OVSystemAPI:
    return OVSystemAPI(client)


OVSystemDep = Annotated[OVSystemAPI, Depends(ov_system_api)]


def ov_admin_api(client: RootOVClient) -> OVAdminAPI:
    return OVAdminAPI(client)


OVAdminDep = Annotated[OVAdminAPI, Depends(ov_admin_api)]


# ---------------------------------------------------------------------------
# JWT 鉴权与初始密码门禁
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)
_AUTH_PATH_PREFIX = "/api/v1/auth/"


def assert_password_current(user: DashboardUser, path: str) -> None:
    """必须先改初始密码；认证自助接口（/api/v1/auth/）放行。"""
    if user.must_change_password and not path.startswith(_AUTH_PATH_PREFIX):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "必须先修改初始密码"
        )


async def get_current_user(
    request: Request,
    db: DBSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> DashboardUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "认证令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("purpose") is not None:
        # bind_token 等带 purpose 的专用短时令牌不得反向充当会话凭据（AUTH-10）
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "认证令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        await db.scalars(
            select(DashboardUser).where(DashboardUser.id == user_id)
        )
    ).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "账号不存在或已禁用"
        )

    assert_password_current(user, request.url.path)
    return user


CurrentUser = Annotated[DashboardUser, Depends(get_current_user)]


def require_roles(*roles: str):
    """角色门禁工厂：角色不符返回 403（经 CurrentUser 链同时执行初始密码门禁）。"""
    allowed = set(roles)

    async def _checker(user: CurrentUser) -> DashboardUser:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"权限不足，需要角色: {', '.join(roles)}",
            )
        return user

    return _checker


AdminUser = Annotated[DashboardUser, Depends(require_roles("admin"))]

ManagerUser = Annotated[DashboardUser, Depends(require_roles("admin", "team_admin"))]
