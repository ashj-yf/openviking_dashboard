"""团队读侧与同步：本地聚合零 OV 调用、详情降级、差异校准。"""
import pytest

from app.services import tenant_service
from app.services.openviking.client import OpenVikingError


async def test_list_tenants_counts_local_only(db, make_tenant, make_user):
    t1 = await make_tenant("acme", display_name="甲")
    t2 = await make_tenant("beta", display_name="乙")
    await make_user("a1", "Passw0rd!", "user", tenant=t1, ov_user_id="a1")
    await make_user("a2", "Passw0rd!", "user", tenant=t1, ov_user_id="a2")
    await make_user("b1", "Passw0rd!", "user", tenant=t2, ov_user_id="b1")

    # list_tenants 签名不含 OV 客户端：列表计数物理上无法触达 OV
    rows = await tenant_service.list_tenants(db, None)
    counts = {t.ov_account_id: c for t, c in rows}
    assert counts == {"acme": 2, "beta": 1}


async def test_list_tenants_search(db, make_tenant):
    await make_tenant("acme", display_name="甲方")
    await make_tenant("beta", display_name="Other")
    rows = await tenant_service.list_tenants(db, "甲")
    assert [t.ov_account_id for t, _ in rows] == ["acme"]
    rows = await tenant_service.list_tenants(db, "beta")
    assert [t.ov_account_id for t, _ in rows] == ["beta"]


async def test_detail_aggregates_ov_sections(db, make_tenant):
    t = await make_tenant("acme")

    class _OV:
        async def get_account(self, aid):
            assert aid == "acme"
            return {"account_id": "acme", "state": "active"}

        async def get_configuration(self, aid):
            return {"retention": 30}

        async def get_settings(self, aid):
            return {"theme": "dark"}

    detail = await tenant_service.get_detail(db, _OV(), t.id)
    assert detail.account_id == "acme"
    assert detail.user_count == 0
    assert detail.ov_account == {"account_id": "acme", "state": "active"}
    assert detail.configuration == {"retention": 30}
    assert detail.settings == {"theme": "dark"}
    assert detail.ov_error is None


async def test_detail_degrades_when_ov_down(db, make_tenant):
    t = await make_tenant("acme")

    class _OV:
        async def get_account(self, aid):
            raise OpenVikingError(502, "upstream down", "/account")

        async def get_configuration(self, aid):
            raise OpenVikingError(502, "upstream down", "/configuration")

        async def get_settings(self, aid):
            raise OpenVikingError(502, "upstream down", "/settings")

    detail = await tenant_service.get_detail(db, _OV(), t.id)
    assert detail.account_id == "acme"
    assert detail.ov_account is None
    assert detail.configuration is None
    assert detail.settings is None
    assert detail.ov_error


async def test_detail_missing_tenant_returns_none(db):
    assert await tenant_service.get_detail(db, object(), 9999) is None


async def test_update_local_fields(db, make_tenant):
    t = await make_tenant("acme")
    updated = await tenant_service.update_local(db, t.id, "新名称", "备注")
    assert updated.display_name == "新名称"
    assert updated.remark == "备注"
    assert await tenant_service.update_local(db, 9999, "x", "y") is None


async def test_sync_reports_differences_and_stamps_time(db, make_tenant, make_user):
    t = await make_tenant("acme")
    await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")

    class _OV:
        async def list_users(self, aid):
            return {"users": [
                {"user_id": "alice", "role": "user"},
                {"user_id": "ghost", "role": "admin"},
            ]}

    report = await tenant_service.sync_users(db, _OV(), t)
    assert report.ov_user_count == 2
    assert report.local_user_count == 1
    assert report.matched == 1
    assert [u["ov_user_id"] for u in report.missing_local] == ["ghost"]
    assert [u["ov_user_id"] for u in report.extra_local] == []
    await db.refresh(t)
    assert t.synced_at is not None
