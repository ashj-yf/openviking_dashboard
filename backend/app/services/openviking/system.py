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
        return await self.c.request("GET", "/api/v1/console/tokens", params=params)

    async def context_commits(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/console/context-commits", params=params)

    async def observer(self, component: str) -> Any:
        if component not in OBSERVER_COMPONENTS:
            raise ValueError(f"未知 observer 组件: {component}")
        return await self.c.request("GET", f"/api/v1/observer/{component}")
