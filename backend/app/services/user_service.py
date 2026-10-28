"""租户内用户注册/删除、角色变更与密钥签发。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.models import AdminUser, KeyRecord, OvUser, Tenant
from app.schemas.ov_user import KeyIssueResult, OvUserCreate
from app.services.openviking.admin import OVAdminAPI
from app.services.openviking.client import OpenVikingError


def _extract_key(payload: object) -> str | None:
    """TODO(填充): 对照实际 key 接口响应调整取值路径。"""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("api_key", "key", "user_key"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return None


async def list_ov_users(db: AsyncSession, tenant: Tenant) -> list[OvUser]:
    return list(
        (
            await db.scalars(
                select(OvUser).where(OvUser.tenant_id == tenant.id).order_by(OvUser.id)
            )
        ).all()
    )


async def get_ov_user(db: AsyncSession, tenant: Tenant, user_id: str) -> OvUser | None:
    return await db.scalar(
        select(OvUser).where(
            OvUser.tenant_id == tenant.id, OvUser.ov_user_id == user_id
        )
    )


async def _upsert_local_user(
    db: AsyncSession, tenant: Tenant, user_id: str, role: str
) -> None:
    existing = await get_ov_user(db, tenant, user_id)
    if existing:
        existing.role = role
    else:
        db.add(OvUser(tenant_id=tenant.id, ov_user_id=user_id, role=role))


async def create_user(
    db: AsyncSession, tenant: Tenant, payload: OvUserCreate, admin: OVAdminAPI
) -> tuple[OvUser, KeyIssueResult | None]:
    ov = await admin.register_user(
        tenant.ov_account_id,
        payload.user_id,
        role=payload.role,
        seed=payload.seed,
    )
    await _upsert_local_user(db, tenant, payload.user_id, payload.role)
    await db.commit()

    user = await get_ov_user(db, tenant, payload.user_id)
    assert user is not None
    api_key = _extract_key(ov)
    result: KeyIssueResult | None = None
    if api_key:
        db.add(
            KeyRecord(
                tenant_id=tenant.id,
                ov_user_id=payload.user_id,
                key_kind="admin" if payload.role == "admin" else "user",
                key_hint=api_key[:8],
                seed_used=payload.seed is not None,
                note="注册用户时签发",
            )
        )
        await db.commit()
        result = KeyIssueResult(
            account_id=tenant.ov_account_id,
            user_id=payload.user_id,
            api_key=api_key,
            key_hint=api_key[:8],
        )
    return user, result


async def delete_user(
    db: AsyncSession, tenant: Tenant, ov_user: OvUser, admin: OVAdminAPI
) -> None:
    if ov_user.ov_user_id == tenant.admin_user_id:
        raise OpenVikingError(400, "不能删除租户的初始管理员用户")
    await admin.delete_user(tenant.ov_account_id, ov_user.ov_user_id)
    await db.delete(ov_user)
    await db.commit()


async def set_role(
    db: AsyncSession, tenant: Tenant, ov_user: OvUser, role: str, admin: OVAdminAPI
) -> None:
    await admin.set_role(tenant.ov_account_id, ov_user.ov_user_id, role)
    ov_user.role = role
    await db.commit()


async def issue_key(
    db: AsyncSession,
    tenant: Tenant,
    ov_user: OvUser,
    seed: str | None,
    admin: OVAdminAPI,
    actor: AdminUser | None,
) -> KeyIssueResult:
    payload = await admin.regenerate_key(
        tenant.ov_account_id, ov_user.ov_user_id, seed=seed
    )
    api_key = _extract_key(payload)
    if not api_key:
        raise OpenVikingError(502, "OpenViking 未返回 api_key 字段，请检查响应结构")

    # 旧记录置为失效
    for record in await db.scalars(
        select(KeyRecord).where(
            KeyRecord.tenant_id == tenant.id,
            KeyRecord.ov_user_id == ov_user.ov_user_id,
            KeyRecord.is_current.is_(True),
        )
    ):
        record.is_current = False

    kind = "admin" if ov_user.role == "admin" else "user"
    db.add(
        KeyRecord(
            tenant_id=tenant.id,
            ov_user_id=ov_user.ov_user_id,
            key_kind=kind,
            key_hint=api_key[:8],
            seed_used=seed is not None,
            issued_by=actor.id if actor else None,
            note="重新签发（旧密钥立即失效）",
        )
    )

    # 若是租户初始管理员，同步更新保管的账户密钥
    if ov_user.ov_user_id == tenant.admin_user_id:
        tenant.admin_key_encrypted = encrypt_secret(api_key)

    await db.commit()
    return KeyIssueResult(
        account_id=tenant.ov_account_id,
        user_id=ov_user.ov_user_id,
        api_key=api_key,
        key_hint=api_key[:8],
    )
