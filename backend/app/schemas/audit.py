"""审计日志查询响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    actor_user_id: int | None = None
    actor_name: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict[str, Any] | None = None
    ip: str | None = None
    created_at: datetime


class AuditLogPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int
