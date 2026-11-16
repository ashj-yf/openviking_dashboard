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

    async def fs_tree(self, uri: str, level_limit: int = 2) -> Any:
        """目录树。

        ``uri`` 必须为 ``viking://`` 形式，裸路径（如 ``/``）服务端 400 INVALID_URI。
        ``level_limit`` 为目录层级上限（服务端默认 3），此处默认 2 沿用旧 depth 语义。
        """
        return await self.c.request(
            "GET", "/api/v1/fs/tree", params={"uri": uri, "level_limit": level_limit}
        )

    async def fs_ls(self, uri: str) -> Any:
        """列目录。``uri`` 必须为 ``viking://`` 形式，裸路径服务端 400 INVALID_URI。"""
        return await self.c.request("GET", "/api/v1/fs/ls", params={"uri": uri})

    async def fs_stat(self, uri: str) -> Any:
        """文件元信息。``uri`` 必须为 ``viking://`` 形式，裸路径服务端 400 INVALID_URI。"""
        return await self.c.request("GET", "/api/v1/fs/stat", params={"uri": uri})

    async def find(self, query: str, **kwargs: Any) -> Any:
        body: dict[str, Any] = {"query": query, **kwargs}
        return await self.c.request("POST", "/api/v1/search/find", json=body)

    async def grep(self, pattern: str, uri: str, **kwargs: Any) -> Any:
        """内容检索。

        ``uri`` 必须为 ``viking://`` 形式，裸路径服务端 400 INVALID_URI；
        ``pattern`` 与 ``uri`` 均为 body 必填字段。
        """
        body: dict[str, Any] = {"pattern": pattern, "uri": uri, **kwargs}
        return await self.c.request("POST", "/api/v1/search/grep", json=body)

    async def acl_get(self, params: dict | None = None) -> Any:
        """读取 ACL。``params`` 必须含必填 query 参数 ``uri``（``viking://`` 形式）。"""
        return await self.c.request("GET", "/api/v1/acl", params=params)
