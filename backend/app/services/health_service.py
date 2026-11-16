"""健康探活：数据库与 OpenViking 双探针独立执行，任一失败降级为 degraded。"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.health import HealthResponse
from app.services.openviking.client import OVClient, root_client
from app.services.openviking.system import OVSystemAPI


async def get_health(db: AsyncSession) -> HealthResponse:
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    ov_ok = False
    version: str | None = None
    client: OVClient | None = None
    try:
        client = root_client()
        payload = await OVSystemAPI(client).health()
        # v0.5.4 包络已在 client 边界剥壳：此处 dict 即响应内层（无 version，缺失即
        # None）；v0.4.x 平铺响应则在顶层携带 version。两种形态统一按 dict 顶层取数。
        if isinstance(payload, dict):
            v = payload.get("version")
            version = v if isinstance(v, str) else None
        ov_ok = True
    except Exception:
        # root key 未配置、HTTP 4xx/5xx、传输错误等任何异常都只做降级，不外抛。
        ov_ok = False
    finally:
        if client is not None:
            await client.aclose()

    return HealthResponse(
        status="ok" if db_ok and ov_ok else "degraded",
        db=db_ok,
        openviking=ov_ok,
        version=version,
    )
