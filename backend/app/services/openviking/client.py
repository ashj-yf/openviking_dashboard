"""OpenViking HTTP 客户端基座。

认证约定（来自 v0.4.x OpenAPI / ov CLI 二进制）：
- 密钥通过 ``Authorization: Bearer <api_key>`` 传递（服务端亦接受 X-API-Key）。
- 数据面可通过 ``X-OpenViking-Account`` / ``X-OpenViking-User`` 断言身份；
  请求按账户自动隔离，非 ROOT 密钥不能跨账户检索。
- ROOT 密钥只能访问 /admin/* 与 /console/*，访问数据面返回 403。
"""
from typing import Any

import httpx

from app.core.config import get_settings


class OpenVikingError(RuntimeError):
    def __init__(self, status_code: int, message: str, path: str = ""):
        self.status_code = status_code
        self.path = path
        super().__init__(f"OpenViking {status_code} {path}: {message}")


class OVClient:
    def __init__(
        self,
        api_key: str,
        *,
        account: str | None = None,
        user: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.openviking_base_url).rstrip("/")
        self.api_key = api_key
        self.account = account
        self.user = user
        self.timeout = timeout or settings.http_timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OVClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if self.account:
            headers["X-OpenViking-Account"] = self.account
        if self.user:
            headers["X-OpenViking-User"] = self.user
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(
                method, url, json=json, params=params, headers=self._headers()
            )
        if resp.status_code >= 400:
            raise OpenVikingError(resp.status_code, resp.text[:500], path)
        if not resp.content:
            return None
        return resp.json()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def root_client() -> OVClient:
    """使用服务端 root key 的管理面客户端。"""
    settings = get_settings()
    if not settings.openviking_root_key:
        raise OpenVikingError(500, "未配置 OPENVIKING_ROOT_KEY")
    return OVClient(settings.openviking_root_key)


def tenant_admin_client(account: str, admin_key: str, *, user: str | None = None) -> OVClient:
    """使用某账户 admin key 的数据面客户端。"""
    return OVClient(admin_key, account=account, user=user)
