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
