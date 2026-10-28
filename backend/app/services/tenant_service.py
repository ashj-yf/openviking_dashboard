"""租户（OpenViking account）业务：本地记录与 Admin API 同步。"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.crypto import encrypt_secret
from app.models import KeyRecord, OvUser, Tenant
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.services.openviking.admin import OVAdminAPI
from app.services.openviking.client import OpenVikingError


def _extract_admin_key(payload: object) -> str | None:
    """OpenViking 创建账户响应中管理员密钥的位置随版本可能不同，集中在此适配。

    TODO(填充): 对照 v0.4.x 实际响应调整，常见位置：
    payload["api_key"] / payload["admin"]["api_key"] / payload["admin_user"]["key"]
    """
    if isinstance(payload, dict):
        for key in ("api_key", "key", "admin_api_key"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        for nested in ("admin", "admin_user", "user"):
            node = payload.get(nested)
            if isinstance(node, dict):
                value = node.get("api_key") or node.get("key")
                if isinstance(value, str):
                    return value
    return None


async def list_tenants(db: AsyncSession) -> list[Tenant]:
    return list((await db.scalars(select(Tenant).order_by(Tenant.id.desc()))).all())


async def get_tenant(db: AsyncSession, tenant_pk: int) -> Tenant | None:
    return await db.get(Tenant, tenant_pk)


async def get_tenant_by_account(db: AsyncSession, account_id: str) -> Tenant | None:
    return await db.scalar(select(Tenant).where(Tenant.ov_account_id == account_id))


async def create_tenant(db: AsyncSession, payload: TenantCreate, admin: OVAdminAPI) -> Tenant:
    ov = await admin.create_account(
        payload.account_id,
        payload.admin_user_id,
        seed=payload.seed,
    )
    admin_key = _extract_admin_key(ov) if payload.save_admin_key else None

    tenant = Tenant(
        ov_account_id=payload.account_id,
        admin_user_id=payload.admin_user_id,
        display_name=payload.display_name,
        remark=payload.remark,
        admin_key_encrypted=encrypt_secret(admin_key) if admin_key else None,
    )
    db.add(tenant)
    await db.flush()

    db.add(
        OvUser(
            tenant_id=tenant.id,
            ov_user_id=payload.admin_user_id,
            role="admin",
        )
    )
    if admin_key:
        db.add(
            KeyRecord(
                tenant_id=tenant.id,
                ov_user_id=payload.admin_user_id,
                key_kind="admin",
                key_hint=admin_key[:8],
                seed_used=payload.seed is not None,
                note="创建租户时签发",
            )
        )
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def update_tenant(db: AsyncSession, tenant: Tenant, payload: TenantUpdate) -> Tenant:
    for field in ("display_name", "remark"):
        value = getattr(payload, field)
        if value is not None:
            setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def delete_tenant(db: AsyncSession, tenant: Tenant, admin: OVAdminAPI) -> None:
    # 先调 OpenViking 删除，远端失败则不删本地
    await admin.delete_account(tenant.ov_account_id)
    await db.delete(tenant)
    await db.commit()


async def sync_users(db: AsyncSession, tenant: Tenant, admin: OVAdminAPI) -> list[OvUser]:
    """从 OpenViking 拉取账户下用户列表并更新本地映射。

    TODO(填充): 实际列表可能是 {"users": [...]} 或直接 [...]，在此归一化。
    """
    payload = await admin.list_users(tenant.ov_account_id)
    remote_users = payload.get("users", payload) if isinstance(payload, dict) else payload
    if not isinstance(remote_users, list):
        raise OpenVikingError(502, f"无法解析用户列表响应: {type(payload).__name__}")

    existing = {u.ov_user_id: u for u in tenant.users}
    seen: set[str] = set()
    for item in remote_users:
        if not isinstance(item, dict):
            continue
        user_id = item.get("user_id") or item.get("id")
        if not user_id:
            continue
        seen.add(user_id)
        if user_id in existing:
            existing[user_id].role = item.get("role", "user")
        else:
            db.add(
                OvUser(
                    tenant_id=tenant.id,
                    ov_user_id=user_id,
                    role=item.get("role", "user"),
                )
            )
    await db.commit()
    await db.refresh(tenant, attribute_names=["users"])
    return tenant.users


async def counts(db: AsyncSession) -> dict[str, int]:
    tenant_count = await db.scalar(select(func.count()).select_from(Tenant))
    user_count = await db.scalar(select(func.count()).select_from(OvUser))
    key_count = await db.scalar(select(func.count()).select_from(KeyRecord))
    return {
        "tenant_count": int(tenant_count or 0),
        "user_count": int(user_count or 0),
        "key_record_count": int(key_count or 0),
    }
