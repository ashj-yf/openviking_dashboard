"""总览看板聚合：本地 KPI + OV 分节透传（分节失败降级 None + 错误消息）。"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DashboardUser, Tenant
from app.schemas.overview import (
    ObserverAggregateOut,
    ObserverComponentOut,
    OverviewSummaryOut,
)
from app.services.openviking.client import OpenVikingError
from app.services.openviking.system import OBSERVER_COMPONENTS, OVSystemAPI

logger = logging.getLogger("app.overview")


async def _ov_section(call: Callable[[], Awaitable[Any]]) -> tuple[Any | None, str | None]:
    """OV 分节调用失败降级为 (None, 错误消息)。

    tenant_service._ov_section 的本地复制件——刻意不跨模块 import 私有函数，
    保持各服务自包含（降级模式约定：凡需降级必须显式 try/except，不依赖全局 handler）。
    """
    try:
        return await call(), None
    except OpenVikingError as exc:
        logger.warning("OV 总览分节降级 path=%s status=%s", exc.path, exc.status_code)
        return None, exc.message


async def build_summary(
    db: AsyncSession, actor: DashboardUser, ov: OVSystemAPI
) -> OverviewSummaryOut:
    """本地 KPI + OV 分节聚合。

    - users_* 恒为团队用户计数（tenant_id 非空；平台 admin 与 LDAP JIT 用户
      tenant_id 为 NULL 天然不计入），team_admin 再收窄到本团队；
    - tenant_count/ov_summary 仅 admin；team_admin 直接跳过 dashboard_summary
      网络调用（根本不请求，而非请求后丢弃）；
    - ov_health 全员可见（OVR-2 顶栏全局健康灯）。
    """
    tenant_count: int | None = None
    if actor.role == "admin":
        tenant_count = (
            await db.scalar(select(func.count()).select_from(Tenant)) or 0
        )

    scope: list[ColumnElement[bool]] = [DashboardUser.tenant_id.isnot(None)]
    if actor.role != "admin":
        scope.append(DashboardUser.tenant_id == actor.tenant_id)
    by_active = {
        active: count
        for active, count in (
            await db.execute(
                select(DashboardUser.is_active, func.count())
                .where(*scope)
                .group_by(DashboardUser.is_active)
            )
        ).all()
    }

    errors: list[str] = []
    ov_summary: dict[str, Any] | None = None
    if actor.role == "admin":
        ov_summary, e1 = await _ov_section(ov.dashboard_summary)
        if e1:
            errors.append(e1)
    ov_health, e2 = await _ov_section(ov.health)
    if e2:
        errors.append(e2)

    return OverviewSummaryOut(
        tenant_count=tenant_count,
        users_total=sum(by_active.values()),
        users_active=by_active.get(True, 0),
        users_disabled=by_active.get(False, 0),
        ov_summary=ov_summary,
        ov_health=ov_health,
        ov_error="；".join(errors) if errors else None,
    )


async def _observer_component(
    ov: OVSystemAPI, component: str
) -> ObserverComponentOut:
    try:
        data = await ov.observer(component)
    except OpenVikingError as exc:
        # 单组件失败只降级本组件（error 非空 + data None），不影响其余组件
        logger.warning(
            "observer 组件降级 component=%s status=%s", component, exc.status_code
        )
        return ObserverComponentOut(data=None, error=exc.message)
    return ObserverComponentOut(data=data, error=None)


async def observer_aggregate(ov: OVSystemAPI) -> ObserverAggregateOut:
    """七组件并发聚合（asyncio.gather）。

    单组件超时依赖 OVClient 的 20s 全局超时，不另做 per-component timeout
    （YAGNI：OV 侧已兜底，Dashboard 侧再设一层只会增加配置面）。
    """
    results = await asyncio.gather(
        *(_observer_component(ov, c) for c in OBSERVER_COMPONENTS)
    )
    return ObserverAggregateOut(components=dict(zip(OBSERVER_COMPONENTS, results)))
