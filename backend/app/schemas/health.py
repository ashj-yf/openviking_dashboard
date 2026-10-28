"""健康检查响应模型。"""
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: bool
    openviking: bool
    version: str | None = None
