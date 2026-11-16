"""OV 数据面薄封装参数契约：fs/grep 实参对齐真机 v0.5.4（uri/level_limit，viking URI）。

真机契约见 tests/fixtures/openapi-v0.5.4.json：
- fs/tree|ls|stat GET query 必填 ``uri``；fs/tree 另有 int 型 ``level_limit``；
- search/grep POST body 必填 ``uri``+``pattern``；search/find POST body 为 ``query``；
- 裸 ``/`` 路径真机 400 INVALID_URI，所有 uri 必须为 ``viking://`` 形式。
"""
import json

import httpx
import pytest

from app.services.openviking.client import OVClient, reset_test_transport, set_test_transport
from app.services.openviking.data import OVDataAPI


@pytest.fixture
def mock_transport():
    handler_holder = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        handler_holder["request"] = request
        return handler_holder["handler"](request)

    set_test_transport(httpx.MockTransport(_handler))
    yield handler_holder
    reset_test_transport()


@pytest.fixture
def api() -> OVDataAPI:
    return OVDataAPI(OVClient("k"))


@pytest.mark.asyncio
async def test_fs_tree_sends_uri_and_level_limit_query(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={"ok": True})

    result = await api.fs_tree("viking://user/u", level_limit=1)

    request = mock_transport["request"]
    assert request.method == "GET"
    assert request.url.path == "/api/v1/fs/tree"
    assert request.url.params["uri"] == "viking://user/u"
    assert request.url.params["level_limit"] == "1"
    assert "path" not in request.url.params
    assert "depth" not in request.url.params
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_fs_tree_default_level_limit_keeps_old_depth_semantics(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.fs_tree("viking://user/u")

    assert mock_transport["request"].url.params["level_limit"] == "2"


@pytest.mark.asyncio
async def test_fs_ls_sends_uri_query(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.fs_ls("viking://user/u")

    request = mock_transport["request"]
    assert request.method == "GET"
    assert request.url.path == "/api/v1/fs/ls"
    assert request.url.params["uri"] == "viking://user/u"
    assert "path" not in request.url.params


@pytest.mark.asyncio
async def test_fs_stat_sends_uri_query(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.fs_stat("viking://user/u")

    request = mock_transport["request"]
    assert request.method == "GET"
    assert request.url.path == "/api/v1/fs/stat"
    assert request.url.params["uri"] == "viking://user/u"
    assert "path" not in request.url.params


@pytest.mark.asyncio
async def test_grep_body_uses_uri_and_pattern(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.grep("p", "viking://user/u")

    request = mock_transport["request"]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/search/grep"
    body = json.loads(request.content)
    assert body["uri"] == "viking://user/u"
    assert body["pattern"] == "p"
    assert "path" not in body


@pytest.mark.asyncio
async def test_grep_kwargs_passthrough(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.grep("p", "viking://user/u", case_insensitive=True)

    assert json.loads(mock_transport["request"].content)["case_insensitive"] is True


@pytest.mark.asyncio
async def test_find_body_still_uses_query(mock_transport, api):
    mock_transport["handler"] = lambda req: httpx.Response(200, json={})

    await api.find("q")

    request = mock_transport["request"]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/search/find"
    assert json.loads(request.content)["query"] == "q"
