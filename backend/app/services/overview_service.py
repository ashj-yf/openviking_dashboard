"""全局总览：本地统计 + OpenViking console/observer 聚合。"""
from app.schemas.overview import LocalStats, ObserverStatus, OverviewSummary
from app.services.openviking.client import OpenVikingError
from app.services.openviking.system import OVSystemAPI
from app.services.tenant_service import counts
from sqlalchemy.ext.asyncio import AsyncSession


async def build_summary(db: AsyncSession, system: OVSystemAPI) -> OverviewSummary:
    local = LocalStats.model_validate(await counts(db))
    ov_payload: dict | None = None
    healthy = True
    try:
        payload = await system.dashboard_summary()
        ov_payload = payload if isinstance(payload, dict) else {"raw": payload}
    except OpenVikingError:
        healthy = False
    return OverviewSummary(local=local, openviking=ov_payload, healthy=healthy)


async def get_observer(system: OVSystemAPI, component: str) -> ObserverStatus:
    try:
        payload = await system.observer(component)
        return ObserverStatus(
            component=component,
            data=payload if isinstance(payload, dict) else {"raw": payload},
        )
    except OpenVikingError:
        return ObserverStatus(component=component, healthy=False)
