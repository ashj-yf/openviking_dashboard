import logging

import httpx
import pytest

from app.services.openviking.client import (
    OVClient,
    OpenVikingError,
    reset_test_transport,
    set_test_transport,
)


@pytest.fixture
def mock_transport():
    handler_holder = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        return handler_holder["handler"](request)

    set_test_transport(httpx.MockTransport(_handler))
    yield handler_holder
    reset_test_transport()


@pytest.mark.asyncio
async def test_request_uses_mock_transport_and_logs_without_secret(mock_transport, caplog):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={"ok": True})
    caplog.set_level(logging.INFO, logger="app.openviking")

    result = await OVClient("secret-key-value").request("GET", "/api/v1/debug/health")

    assert result == {"ok": True}
    assert "ov_request" in caplog.text
    assert "/api/v1/debug/health" in caplog.text and "200" in caplog.text
    assert "secret-key-value" not in caplog.text
    assert "Authorization" not in caplog.text


@pytest.mark.asyncio
async def test_error_response_raises_with_message_field(mock_transport):
    mock_transport["handler"] = lambda req: httpx.Response(500, text="boom")
    with pytest.raises(OpenVikingError) as exc:
        await OVClient("k").request("GET", "/x")
    assert exc.value.status_code == 500
    assert exc.value.message == "boom"
    assert exc.value.path == "/x"


@pytest.mark.asyncio
async def test_empty_body_returns_none(mock_transport):
    mock_transport["handler"] = lambda req: httpx.Response(204)
    assert await OVClient("k").request("DELETE", "/x") is None


@pytest.mark.asyncio
async def test_connect_error_wrapped_as_503(mock_transport):
    """httpx 连接级异常（HTTPError 子类）统一包装为 OpenVikingError(503)。"""

    def _boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    mock_transport["handler"] = _boom
    with pytest.raises(OpenVikingError) as exc:
        await OVClient("secret-key-value").request("GET", "/x")
    assert exc.value.status_code == 503
    assert exc.value.message == "OpenViking 连接失败: ConnectError"
    assert exc.value.path == "/x"
    # 消息不含 URL 参数与密钥
    assert "secret-key-value" not in exc.value.message
    assert "http" not in exc.value.message


@pytest.mark.asyncio
async def test_envelope_success_returns_inner_result(mock_transport):
    mock_transport["handler"] = lambda req: httpx.Response(
        200,
        json={"status": "ok", "result": {"user_id": "u1"}, "error": None},
    )

    result = await OVClient("k").request("GET", "/api/v1/users/me")

    assert result == {"user_id": "u1"}


@pytest.mark.asyncio
async def test_flat_payload_without_result_passes_through(mock_transport):
    for payload in ({"status": "ok"}, {"ok": True}):
        mock_transport["handler"] = lambda req, payload=payload: httpx.Response(
            200, json=payload
        )

        result = await OVClient("k").request("GET", "/api/v1/debug/health")

        assert result == payload


@pytest.mark.asyncio
async def test_result_without_status_passes_through(mock_transport):
    # AND 判定第三腿：有 result 无 status 的形态不剥壳，原样返回
    mock_transport["handler"] = lambda req: httpx.Response(200, json={"result": {"a": 1}})

    result = await OVClient("k").request("GET", "/x")

    assert result == {"result": {"a": 1}}


@pytest.mark.asyncio
async def test_error_envelope_still_raises(mock_transport):
    mock_transport["handler"] = lambda req: httpx.Response(
        400, json={"status": "error", "error": {"code": "INVALID_ARGUMENT"}}
    )

    with pytest.raises(OpenVikingError) as exc:
        await OVClient("k").request("POST", "/api/v1/data/query")

    assert exc.value.status_code == 400
