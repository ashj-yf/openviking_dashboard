from typing import Any

from pydantic import BaseModel


class LocalStats(BaseModel):
    tenant_count: int
    user_count: int
    key_record_count: int


class OverviewSummary(BaseModel):
    """全局总览：本地统计 + OpenViking console/dashboard/summary 透传。"""

    local: LocalStats
    openviking: dict[str, Any] | None = None
    healthy: bool = True


class ObserverStatus(BaseModel):
    component: str
    data: dict[str, Any] | None = None
    healthy: bool = True
