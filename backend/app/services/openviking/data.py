"""数据面 API 封装：用账户 admin key 访问，用于"用户看板"。

root key 访问数据面会 403；admin key 按所在 account 自动隔离。
具体返回结构以服务端 OpenAPI/实际响应为准，这里先做薄封装、原样透传。
"""
from typing import Any

from app.services.openviking.client import OVClient


class OVDataAPI:
    def __init__(self, client: OVClient):
        self.c = client

    async def list_skills(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/skills", params=params)

    async def list_resources(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/resources", params=params)

    async def list_sessions(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/sessions", params=params)

    async def fs_tree(self, path: str = "/", depth: int = 2) -> Any:
        return await self.c.request(
            "GET", "/api/v1/fs/tree", params={"path": path, "depth": depth}
        )

    async def fs_ls(self, path: str = "/") -> Any:
        return await self.c.request("GET", "/api/v1/fs/ls", params={"path": path})

    async def fs_stat(self, path: str) -> Any:
        return await self.c.request("GET", "/api/v1/fs/stat", params={"path": path})

    async def find(self, query: str, **kwargs: Any) -> Any:
        body: dict[str, Any] = {"query": query, **kwargs}
        return await self.c.request("POST", "/api/v1/search/find", json=body)

    async def grep(self, pattern: str, path: str = "/", **kwargs: Any) -> Any:
        body: dict[str, Any] = {"pattern": pattern, "path": path, **kwargs}
        return await self.c.request("POST", "/api/v1/search/grep", json=body)

    async def acl_get(self, params: dict | None = None) -> Any:
        return await self.c.request("GET", "/api/v1/acl", params=params)
