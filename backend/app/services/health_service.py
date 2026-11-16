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
        await OVSystemAPI(client).health()
        ov_ok = True
    except Exception:
        # root key 未配置、HTTP 4xx/5xx、传输错误等任何异常都只做降级，不外抛。
        ov_ok = False

    if client is not None:
        # 版本探测：根路径 /health 免鉴权，v0.5.4 真机为平铺响应
        # {"status","healthy","version","auth_mode"}（有 status 无 result，client 剥壳原样透传）。
        # 任何失败（异常/缺字段/非 str）仅降级 version=None，不影响 ov_ok 探活语义。
        try:
            payload = await client.request("GET", "/health")
            if isinstance(payload, dict):
                v = payload.get("version")
                version = v if isinstance(v, str) else None
        except Exception:
            version = None
        finally:
            await client.aclose()

    return HealthResponse(
        status="ok" if db_ok and ov_ok else "degraded",
        db=db_ok,
        openviking=ov_ok,
        version=version,
    )
