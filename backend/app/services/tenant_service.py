"""团队领域逻辑：列表/详情聚合/本地编辑/同步；创建与删除在 Task 3 追加。"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DashboardUser, Tenant
from app.schemas.tenant import (
    SyncUserInfo,
    TenantDetailOut,
    TenantListItem,
    TenantSyncReport,
)
from app.services.openviking.client import OpenVikingError
from app.services.openviking.payloads import (
    extract_remote_role,
    extract_remote_user_id,
    extract_users_list,
)

logger = logging.getLogger("app.tenant")


async def list_tenants(
    db: AsyncSession, q: str | None
) -> list[tuple[Tenant, int]]:
    """本地聚合用户数，一条 group_by 查询，不触达 OV。"""
    stmt = (
        select(Tenant, func.count(DashboardUser.id))
        .outerjoin(DashboardUser, DashboardUser.tenant_id == Tenant.id)
        .group_by(Tenant.id)
        .order_by(Tenant.id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Tenant.ov_account_id.ilike(like), Tenant.display_name.ilike(like))
        )
    return list((await db.execute(stmt)).all())


async def _ov_section(call) -> tuple[object | None, str | None]:
    try:
        return await call(), None
    except OpenVikingError as exc:
        logger.warning("OV 聚合区降级 path=%s status=%s", exc.path, exc.status_code)
        return None, exc.message


async def get_detail(db: AsyncSession, admin_api, tenant_id: int):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    count = await db.scalar(
        select(func.count())
        .select_from(DashboardUser)
        .where(DashboardUser.tenant_id == tenant_id)
    )
    ov_account, e1 = await _ov_section(lambda: admin_api.get_account(tenant.ov_account_id))
    configuration, e2 = await _ov_section(
        lambda: admin_api.get_configuration(tenant.ov_account_id)
    )
    settings, e3 = await _ov_section(lambda: admin_api.get_settings(tenant.ov_account_id))
    errors = [e for e in (e1, e2, e3) if e]
    return TenantDetailOut(
        id=tenant.id,
        account_id=tenant.ov_account_id,
        display_name=tenant.display_name,
        remark=tenant.remark,
        admin_user_id=tenant.admin_user_id,
        user_count=count or 0,
        synced_at=tenant.synced_at,
        created_at=tenant.created_at,
        ov_account=ov_account,
        configuration=configuration,
        settings=settings,
        ov_error="；".join(errors) if errors else None,
    )


async def update_local(
    db: AsyncSession, tenant_id: int, display_name: str | None, remark: str | None
) -> Tenant | None:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    if display_name is not None:
        tenant.display_name = display_name
    if remark is not None:
        tenant.remark = remark
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def sync_users(db: AsyncSession, admin_api, tenant: Tenant) -> TenantSyncReport:
    """以 OV 用户列表校准本地映射；只报告差异，不自动建账（Q：绑定已有 OV 用户默认不允许）。"""
    payload = await admin_api.list_users(tenant.ov_account_id)
    remote = {}
    for u in extract_users_list(payload):
        uid = extract_remote_user_id(u)
        if uid:
            remote[uid] = extract_remote_role(u)

    locals_ = (
        await db.scalars(
            select(DashboardUser).where(DashboardUser.tenant_id == tenant.id)
        )
    ).all()
    local_map = {u.ov_user_id: u for u in locals_}

    missing_local = [
        SyncUserInfo(ov_user_id=uid, ov_role=role)
        for uid, role in remote.items()
        if uid not in local_map
    ]
    extra_local = [
        SyncUserInfo(ov_user_id=u.ov_user_id, username=u.username)
        for uid, u in local_map.items()
        if uid not in remote
    ]
    matched = len(set(remote) & set(local_map))

    tenant.synced_at = datetime.now(timezone.utc)
    await db.commit()

    return TenantSyncReport(
        account_id=tenant.ov_account_id,
        ov_user_count=len(remote),
        local_user_count=len(local_map),
        matched=matched,
        missing_local=missing_local,
        extra_local=extra_local,
        synced_at=tenant.synced_at,
    )


async def user_count(db: AsyncSession, tenant_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(DashboardUser).where(
            DashboardUser.tenant_id == tenant_id
        )
    ) or 0


async def get_raw(db: AsyncSession, tenant_id: int) -> Tenant | None:
    return await db.get(Tenant, tenant_id)
