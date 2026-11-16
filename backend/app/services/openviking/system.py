"""控制台与可观测性端点：全局总览、审计、Observer 组件状态。"""
from typing import Any

from app.services.openviking.client import OVClient

OBSERVER_COMPONENTS = (
    "queue",
    "models",
    "retrieval",
    "system",
    "vikingdb",
    "filesystem",
    "lock",
)


class OVSystemAPI:
    def __init__(self, client: OVClient):
        self.c = client

    async def health(self) -> Any:
        return await self.c.request("GET", "/api/v1/debug/health")

    async def dashboard_summary(self) -> Any:
        return await self.c.request("GET", "/api/v1/console/dashboard/summary")

    async def console_audit(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/console/audit", params=params)

    async def console_tokens(self, params: dict | None = None) -> Any:
        """Token 用量趋势。必填 query 参数 ``start_date``/``end_date``（``YYYY-MM-DD``）
        经 ``params`` 透传，裸调服务端 400 INVALID_ARGUMENT；可选 ``bucket``（默认
        ``day``）与 ``timezone``（IANA 名，缺省服务端时区）。当前无产品调用方，
        不在此封装默认日期。
        """
        return await self.c.request("GET", "/api/v1/console/tokens", params=params)

    async def context_commits(self, params: dict | None = None) -> Any:
        """上下文写入热力图。必填 query 参数 ``start_date``/``end_date``
        （``YYYY-MM-DD``）经 ``params`` 透传，裸调服务端 400 INVALID_ARGUMENT；
        可选 ``bucket``（``hour``/``4h``，默认 ``hour``）与 ``timezone``。当前无
        产品调用方，不在此封装默认日期。
        """
        return await self.c.request("GET", "/api/v1/console/context-commits", params=params)

    async def observer(self, component: str) -> Any:
        if component not in OBSERVER_COMPONENTS:
            raise ValueError(f"未知 observer 组件: {component}")
        return await self.c.request("GET", f"/api/v1/observer/{component}")
