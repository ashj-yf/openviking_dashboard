"""SPA 静态产物托管测试。

约定（见 docs/Features/08-deployment.md §3）：
- 仅当静态产物目录存在时才挂载 StaticFiles 到 "/"；
- /healthz、/api/v1/* 路由优先于静态挂载；
- 非 /api、非 /healthz 的 GET 在静态文件缺失时回退 index.html（前端路由自管 404）；
- 静态目录缺失（本地开发）时应用照常启动，API 不受影响。
"""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main as main_module
from app.core.db import get_session

INDEX_HTML = "<!doctype html><html><body>SPA_INDEX_MARKER</body></html>"
APP_JS = "console.log('SPA_ASSET_MARKER');"


@pytest.fixture
def spa_client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "app.js").write_text(APP_JS, encoding="utf-8")
    monkeypatch.setattr(main_module, "STATIC_DIR", dist)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'spa.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app = main_module.create_app()
    app.dependency_overrides[get_session] = _override_get_session

    # OV 探活在测试中一律打桩为不可用，杜绝真实网络并验证降级语义。
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="down"))

    from app.services.openviking.client import reset_test_transport, set_test_transport

    set_test_transport(transport)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_test_transport()


def test_root_serves_index(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "SPA_INDEX_MARKER" in resp.text


def test_frontend_deep_link_falls_back_to_index(spa_client):
    resp = spa_client.get("/tenants")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "SPA_INDEX_MARKER" in resp.text


def test_missing_static_asset_path_falls_back_to_index(spa_client):
    # 非 API 的任意深链（含伪装成资源的路径）都回退 index.html，由前端路由自管 404。
    resp = spa_client.get("/assets/does-not-exist.js")
    assert resp.status_code == 200
    assert "SPA_INDEX_MARKER" in resp.text


def test_existing_asset_served(spa_client):
    resp = spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "SPA_ASSET_MARKER" in resp.text
    assert "SPA_INDEX_MARKER" not in resp.text


def test_unknown_api_path_returns_json_404(spa_client):
    resp = spa_client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert "SPA_INDEX_MARKER" not in resp.text
    assert "detail" in resp.json()


def test_healthz_takes_precedence(spa_client):
    resp = spa_client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is True
    # OV 打桩 503：降级为 false 但不影响 200。
    assert body["openviking"] is False


def test_app_starts_without_static_dir(tmp_path, monkeypatch):
    missing = tmp_path / "no-dist-here"
    monkeypatch.setattr(main_module, "STATIC_DIR", missing)

    app = main_module.create_app()
    mounted = [getattr(r, "name", "") for r in app.routes]
    assert "spa-static" not in mounted

    with TestClient(app) as client:
        # 无静态挂载：未知页面路径走默认 JSON 404，而不是 HTML。
        resp = client.get("/")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")

        # API 路由照常注册并返回 JSON 404。
        resp_api = client.get("/api/v1/does-not-exist")
        assert resp_api.status_code == 404
        assert resp_api.headers["content-type"].startswith("application/json")
