"""总览看板路由：summary（admin/team_admin）与 observer（admin only）。"""
from fastapi import APIRouter, HTTPException, status

from app.core.deps import AdminUser, DBSession, ManagerUser, OVSystemDep
from app.schemas.overview import (
    ObserverAggregateOut,
    ObserverComponentOut,
    OverviewSummaryOut,
)
from app.services.openviking.system import OBSERVER_COMPONENTS
from app.services.overview_service import build_summary, observer_aggregate

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("/summary", response_model=OverviewSummaryOut)
async def get_summary(
    db: DBSession, actor: ManagerUser, ov: OVSystemDep
) -> OverviewSummaryOut:
    """本地 KPI + OV 分节聚合；OV 故障时分节降级，不拖垮页面。"""
    return await build_summary(db, actor, ov)


@router.get("/observer", response_model=ObserverAggregateOut)
async def get_observer_aggregate(
    _: AdminUser, ov: OVSystemDep
) -> ObserverAggregateOut:
    """七组件并发聚合，部分失败不影响其余组件。"""
    return await observer_aggregate(ov)


@router.get("/observer/{component}", response_model=ObserverComponentOut)
async def get_observer_component(
    component: str, _: AdminUser, ov: OVSystemDep
) -> ObserverComponentOut:
    """单组件状态透传；OV 错误冒泡走全局 OpenVikingError handler。"""
    if component not in OBSERVER_COMPONENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未知 observer 组件")
    return ObserverComponentOut(data=await ov.observer(component), error=None)
