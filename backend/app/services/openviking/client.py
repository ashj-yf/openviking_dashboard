"""OpenViking HTTP 客户端基座。

认证约定（来自 v0.4.x OpenAPI / ov CLI 二进制）：
- 密钥通过 ``Authorization: Bearer <api_key>`` 传递（服务端亦接受 X-API-Key）。
- 数据面可通过 ``X-OpenViking-Account`` / ``X-OpenViking-User`` 断言身份；
  请求按账户自动隔离，非 ROOT 密钥不能跨账户检索。
- ROOT 密钥只能访问 /admin/* 与 /console/*，访问数据面返回 403。
"""
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("app.openviking")

# 测试注入缝：None 表示走真实网络；测试通过 set_test_transport 注入 MockTransport。
_test_transport: httpx.AsyncBaseTransport | None = None


def set_test_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """注入测试用 httpx transport（如 ``httpx.MockTransport``）。"""
    global _test_transport
    _test_transport = transport


def reset_test_transport() -> None:
    """清除测试注入的 transport，恢复真实网络。"""
    global _test_transport
    _test_transport = None


class OpenVikingError(RuntimeError):
    def __init__(self, status_code: int, message: str, path: str = ""):
        self.status_code = status_code
        self.message = message
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
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self.timeout, transport=_test_transport) as client:
            try:
                resp = await client.request(
                    method, url, json=json, params=params, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                # 连接级异常（ConnectError/TimeoutException 等）统一包装为 503，
                # 供分节降级与全局 handler 语义复用；消息只含异常类型名，
                # 不含 URL 参数与密钥。
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.warning(
                    "ov_request method=%s path=%s status=503 elapsed_ms=%.1f error=%s",
                    method,
                    path,
                    elapsed_ms,
                    type(exc).__name__,
                )
                raise OpenVikingError(
                    503, f"OpenViking 连接失败: {type(exc).__name__}", path
                ) from exc
        elapsed_ms = (time.monotonic() - start) * 1000
        # 只记录方法/路径/状态码/耗时；禁止记录 headers、body、params 与 api_key。
        logger.info(
            "ov_request method=%s path=%s status=%s elapsed_ms=%.1f",
            method,
            path,
            resp.status_code,
            elapsed_ms,
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
