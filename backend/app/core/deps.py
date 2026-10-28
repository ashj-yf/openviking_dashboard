"""FastAPI 依赖注入：数据库会话、当前登录用户、OpenViking API 工厂。"""
from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import AdminUser, Tenant
from app.services.openviking.admin import OVAdminAPI
from app.services.openviking.client import OVClient, OpenVikingError, root_client, tenant_admin_client
from app.services.openviking.data import OVDataAPI
from app.services.openviking.system import OVSystemAPI
from app.services.tenant_service import get_tenant

DBSession = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def get_current_admin(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> AdminUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少认证令牌")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "认证令牌无效或已过期")
    user = await db.get(AdminUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已禁用")
    return user


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


async def _root_ov() -> AsyncGenerator[OVClient, None]:
    try:
        client = root_client()
    except OpenVikingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    yield client
    await client.aclose()


RootOVClient = Annotated[OVClient, Depends(_root_ov)]


def ov_admin_api(client: RootOVClient) -> OVAdminAPI:
    return OVAdminAPI(client)


def ov_system_api(client: RootOVClient) -> OVSystemAPI:
    return OVSystemAPI(client)


OVAdminDep = Annotated[OVAdminAPI, Depends(ov_admin_api)]
OVSystemDep = Annotated[OVSystemAPI, Depends(ov_system_api)]


async def get_tenant_or_404(db: DBSession, tenant_id: int) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "租户不存在")
    return tenant


def tenant_data_api(
    request: Request, tenant: Annotated[Tenant, Depends(get_tenant_or_404)]
) -> OVDataAPI:
    """使用租户保管的 admin key 构建数据面客户端。

    可选 X-OpenViking-User 请求头将看板视角切换到具体用户。
    """
    if not tenant.admin_key_encrypted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该租户未保管 admin key，无法代理数据面请求（请重新签发管理员密钥）",
        )
    from app.core.crypto import decrypt_secret

    act_as = request.headers.get("X-OpenViking-User")
    client = tenant_admin_client(
        tenant.ov_account_id, decrypt_secret(tenant.admin_key_encrypted), user=act_as
    )
    return OVDataAPI(client)


TenantDataDep = Annotated[OVDataAPI, Depends(tenant_data_api)]
