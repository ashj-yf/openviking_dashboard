"""总览看板响应模型。"""
from typing import Any

from pydantic import BaseModel


class OverviewSummaryOut(BaseModel):
    tenant_count: int | None = None  # team_admin 恒 None
    users_total: int = 0
    users_active: int = 0
    users_disabled: int = 0
    ov_summary: dict[str, Any] | None = None  # admin only，原样透传（Q7）
    ov_health: dict[str, Any] | None = None  # 原样透传（字段待抓包）
    ov_error: str | None = None


class ObserverComponentOut(BaseModel):
    data: dict[str, Any] | None = None
    error: str | None = None


class ObserverAggregateOut(BaseModel):
    components: dict[str, ObserverComponentOut]
