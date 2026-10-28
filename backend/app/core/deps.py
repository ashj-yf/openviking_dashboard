"""FastAPI 依赖：数据库会话与 root key OV 客户端。"""
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
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
