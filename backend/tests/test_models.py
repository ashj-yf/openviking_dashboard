import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import AuditLog, DashboardUser, Tenant


async def test_encrypt_roundtrip_uses_secret_key():
    token = encrypt_secret("ov-user-secret-token")
    assert token != "ov-user-secret-token"
    assert decrypt_secret(token) == "ov-user-secret-token"


async def test_create_tenant_and_bound_user(db):
    tenant = Tenant(ov_account_id="acme", admin_user_id="boss")
    db.add(tenant)
    await db.flush()
    db.add(
        DashboardUser(
            username="boss",
            password_hash="x" * 60,
            role="team_admin",
            tenant_id=tenant.id,
            ov_user_id="boss",
            ov_role="admin",
            ov_user_key_encrypted=encrypt_secret("ov-user-secret-token"),
        )
    )
    await db.commit()

    loaded = (await db.scalars(select(DashboardUser).where(DashboardUser.username == "boss"))).one()
    assert loaded.tenant.ov_account_id == "acme"
    assert loaded.must_change_password is False
    assert decrypt_secret(loaded.ov_user_key_encrypted) == "ov-user-secret-token"


async def test_platform_admin_has_null_tenant(db):
    db.add(DashboardUser(username="root-admin", password_hash="x" * 60, role="admin"))
    await db.commit()
    count = await db.scalar(select(func.count()).select_from(DashboardUser))
    assert count == 1


async def test_duplicate_ov_user_within_tenant_rejected(db):
    tenant = Tenant(ov_account_id="acme", admin_user_id="boss")
    db.add(tenant)
    await db.flush()
    for name in ("a", "b"):
        db.add(DashboardUser(username=name, password_hash="x" * 60, role="user",
                            tenant_id=tenant.id, ov_user_id="same-id", ov_role="user"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_audit_log_actor_columns(db):
    db.add(AuditLog(actor_user_id=None, actor_name="unknown", action="auth.login.fail", ip="127.0.0.1"))
    await db.commit()
    row = (await db.scalars(select(AuditLog))).one()
    assert row.action == "auth.login.fail" and row.actor_user_id is None
