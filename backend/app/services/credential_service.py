"""我的凭证：组装视图、打码、显式暴露（审计）、自助重签。"""
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.models import DashboardUser
from app.schemas.credential import CredentialView, RevealedKeyOut
from app.services import audit_service, user_service


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    stars = min(12, len(key) - 8)
    return f"{key[:4]}{'*' * stars}{key[-4:]}"


async def _bound_identity(user: DashboardUser) -> tuple[str, str]:
    if user.tenant_id is None or not user.ov_user_id or user.tenant is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "当前账号未绑定 OpenViking 身份"
        )
    return user.tenant.ov_account_id, user.ov_user_id


async def _build_view(db: AsyncSession, user: DashboardUser) -> CredentialView:
    account_id, ov_user_id = await _bound_identity(user)
    record = await user_service.current_key_record(db, user.id)
    has_key = bool(user.ov_user_key_encrypted)
    masked = None
    if has_key:
        masked = mask_key(decrypt_secret(user.ov_user_key_encrypted))
    return CredentialView(
        endpoint=get_settings().openviking_base_url,
        account_id=account_id,
        ov_user_id=ov_user_id,
        has_key=has_key,
        key_masked=masked,
        key_hint=record.key_hint if record else None,
        seed_used=record.seed_used if record else False,
        key_synced_at=user.key_synced_at,
    )


async def get_view(db: AsyncSession, user: DashboardUser) -> CredentialView:
    return await _build_view(db, user)


async def expose(db: AsyncSession, user: DashboardUser, action: str,
                 ip: str | None) -> RevealedKeyOut:
    await _bound_identity(user)
    if not user.ov_user_key_encrypted:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "凭证尚未托管，请先重签 key"
        )
    view = await _build_view(db, user)
    plain = decrypt_secret(user.ov_user_key_encrypted)
    await audit_service.record(
        db, action, actor=user, target_type="dashboard_user",
        target_id=str(user.id), ip=ip,
    )
    return RevealedKeyOut(**view.model_dump(), key=plain)


async def regenerate_self(db, admin_api, user: DashboardUser, seed, ip) -> RevealedKeyOut:
    plain = await user_service.rotate_user_key(
        db, admin_api, user, user, seed=seed, ip=ip, action="key.regenerate"
    )
    view = await _build_view(db, user)
    return RevealedKeyOut(**view.model_dump(), key=plain)
