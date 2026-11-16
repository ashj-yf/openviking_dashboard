import httpx

from app.services import health_service


async def test_health_all_green(db, ov_mock):
    ov_mock["handler"] = lambda req: httpx.Response(200, json={"status": "ok", "version": "v0.4.13"})
    result = await health_service.get_health(db)
    assert result.db is True and result.openviking is True
    assert result.version == "v0.4.13"


async def test_health_non_string_version_reported_none(db, ov_mock):
    ov_mock["handler"] = lambda req: httpx.Response(200, json={"status": "ok", "version": 123})
    result = await health_service.get_health(db)
    assert result.db is True and result.openviking is True
    assert result.version is None


async def test_health_v054_envelope_inner_no_version(db, ov_mock):
    # v0.5.4 真机包络经 client 剥壳后 health() 返回内层，内层无 version 字段
    ov_mock["handler"] = lambda req: httpx.Response(
        200, json={"status": "ok", "result": {"healthy": True, "account_id": "default"}}
    )
    result = await health_service.get_health(db)
    assert result.db is True and result.openviking is True
    assert result.version is None


async def test_health_ov_down_still_db_ok(db, ov_mock):
    ov_mock["handler"] = lambda req: httpx.Response(500, text="boom")
    result = await health_service.get_health(db)
    assert result.db is True and result.openviking is False


async def test_health_missing_root_key_reports_false(db, monkeypatch):
    from app.core import config as config_module
    monkeypatch.setattr(config_module.get_settings(), "openviking_root_key", "")
    result = await health_service.get_health(db)
    assert result.db is True and result.openviking is False


async def test_health_db_failure(ov_mock):
    # 指向不可能创建的目录：连接阶段即 OperationalError → db=false
    ov_mock["handler"] = lambda req: httpx.Response(200, json={"status": "ok"})
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    eng = create_async_engine("sqlite+aiosqlite:////nonexistent-dir-ovdash/cannot.db")
    factory = async_sessionmaker(eng)
    async with factory() as session:
        result = await health_service.get_health(session)
    await eng.dispose()
    assert result.db is False


async def test_healthz_route_200_when_ov_down(client, ov_mock):
    ov_mock["handler"] = lambda req: httpx.Response(503, text="down")
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is True and body["openviking"] is False
    assert body["status"] == "degraded"
