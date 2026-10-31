"""key_records 模型、SQLite 外键级联与审计 SET NULL。"""
import pytest
from sqlalchemy import select

from app.models import AuditLog, DashboardUser, KeyRecord


async def test_sqlite_foreign_keys_enabled(engine):
    from sqlalchemy import text
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_key_record_current_partial_unique(db, make_user):
    user = await make_user("alice", "Passw0rd!", "user",
                           tenant={"ov_account_id": "acme", "admin_user_id": "boss"},
                           ov_user_id="alice")
    db.add(KeyRecord(tenant_id=user.tenant_id, dashboard_user_id=user.id,
                     ov_user_id="alice", key_kind="user", key_hint="k" * 8))
    await db.commit()
    db.add(KeyRecord(tenant_id=user.tenant_id, dashboard_user_id=user.id,
                     ov_user_id="alice", key_kind="user", key_hint="n" * 8,
                     is_current=True))
    with pytest.raises(Exception):
        await db.commit()


async def test_delete_user_cascades_records_and_nulls_audit(db, make_user):
    user = await make_user("alice", "Passw0rd!", "user",
                           tenant={"ov_account_id": "acme", "admin_user_id": "boss"},
                           ov_user_id="alice")
    db.add(KeyRecord(tenant_id=user.tenant_id, dashboard_user_id=user.id,
                     ov_user_id="alice", key_kind="user", key_hint="k" * 8))
    db.add(AuditLog(actor_user_id=user.id, actor_name="alice",
                    action="key.view", target_type="dashboard_user", target_id=str(user.id)))
    await db.commit()
    await db.delete(user)
    await db.commit()
    assert (await db.scalars(select(KeyRecord))).all() == []
    log = (await db.scalars(select(AuditLog))).one()
    assert log.actor_user_id is None
    assert log.actor_name == "alice"


async def test_delete_tenant_cascades_users_and_records(db, make_user, make_tenant):
    tenant = await make_tenant("acme")
    user = await make_user("alice", "Passw0rd!", "user", tenant=tenant, ov_user_id="alice")
    db.add(KeyRecord(tenant_id=tenant.id, dashboard_user_id=user.id,
                     ov_user_id="alice", key_kind="user", key_hint="k" * 8))
    await db.commit()
    await db.delete(tenant)
    await db.commit()
    assert (await db.scalars(select(DashboardUser))).all() == []
    assert (await db.scalars(select(KeyRecord))).all() == []
