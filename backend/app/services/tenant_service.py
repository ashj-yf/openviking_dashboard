"""团队领域逻辑：列表/详情聚合/本地编辑/同步/创建/硬删。"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.core.security import hash_password
from app.models import DashboardUser, KeyRecord, Tenant
from app.schemas.tenant import (
    SyncUserInfo,
    TenantCreatedOut,
    TenantCreateRequest,
    TenantDetailOut,
    TenantSyncReport,
)
from app.services import audit_service
from app.services.openviking.client import OpenVikingError
from app.services.openviking.payloads import (
    extract_admin_key,
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


async def create_tenant(
    db: AsyncSession, admin_api, actor, payload: TenantCreateRequest, *, ip: str | None
) -> TenantCreatedOut:
    # 本地先拦重复，避免无谓 OV 调用
    exists = await db.scalar(
        select(Tenant).where(Tenant.ov_account_id == payload.account_id)
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "团队 account_id 已存在")

    username_exists = await db.scalar(
        select(DashboardUser).where(DashboardUser.username == payload.admin_username)
    )
    if username_exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "登录名已存在")

    # 先 OV：OV 失败时本地零写入（OpenVikingError 由全局处理器透传）
    resp = await admin_api.create_account(
        payload.account_id,
        payload.admin_user_id,
        seed=payload.seed,
    )

    tenant = Tenant(
        ov_account_id=payload.account_id,
        admin_user_id=payload.admin_user_id,
        display_name=payload.display_name,
        remark=payload.remark,
    )
    db.add(tenant)
    try:
        await db.flush()  # 拿到 tenant.id
    except Exception:  # noqa: BLE001 - re-raised as HTTP 500 below
        logger.error("OV 账户已创建但本地 tenants 落库失败 account=%s", payload.account_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "OpenViking 账户已创建但本地记录失败，请在列表执行同步补偿",
        )

    # 初始 team_admin：先落用户行拿到 id，再写 key_record
    admin_key = extract_admin_key(resp)
    team_admin = DashboardUser(
        username=payload.admin_username,
        password_hash=hash_password(payload.admin_password),
        role="team_admin",
        is_active=True,  # 初始 team_admin 允许先登录改密；key 缺失时凭证页提示重签
        tenant_id=tenant.id,
        ov_user_id=payload.admin_user_id,
        ov_role="admin",
        ov_user_key_encrypted=encrypt_secret(admin_key) if admin_key else None,
        key_synced_at=datetime.now(timezone.utc) if admin_key else None,
        must_change_password=True,
    )
    db.add(team_admin)
    await db.flush()  # 拿到 team_admin.id
    if admin_key:
        db.add(KeyRecord(
            tenant_id=tenant.id,
            dashboard_user_id=team_admin.id,
            ov_user_id=payload.admin_user_id,
            key_kind="admin",
            key_hint=admin_key[:8],
            seed_used=payload.seed is not None,
            issued_by=actor.id if actor else None,
        ))
    await db.commit()

    await audit_service.record(
        db, "tenant.create", actor=actor,
        target_type="tenant", target_id=payload.account_id,
        detail={"display_name": payload.display_name, "key_provisioned": bool(admin_key)},
        ip=ip,
    )
    await audit_service.record(
        db, "user.create", actor=actor,
        target_type="dashboard_user", target_id=str(team_admin.id),
        detail={"source": "tenant_init_admin", "tenant": payload.account_id,
                "username": payload.admin_username, "key_provisioned": bool(admin_key),
                "seed_used": payload.seed is not None},
        ip=ip,
    )

    return TenantCreatedOut(
        id=tenant.id,
        account_id=payload.account_id,
        admin_user_id=payload.admin_user_id,
        team_admin_id=team_admin.id,
        team_admin_username=team_admin.username,
        key_provisioned=bool(admin_key),
    )


async def delete_tenant(
    db: AsyncSession, admin_api, tenant_id: int, *, confirm: bool,
    actor, ip: str | None,
) -> None:
    if not confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请确认删除操作")
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")
    try:
        await admin_api.delete_account(tenant.ov_account_id)
    except OpenVikingError:
        await audit_service.record(
            db, "tenant.delete.fail", actor=actor, target_type="tenant",
            target_id=tenant.ov_account_id, ip=ip,
        )
        raise
    await audit_service.record(
        db, "tenant.delete", actor=actor, target_type="tenant",
        target_id=tenant.ov_account_id,
        detail={"user_count": await user_count(db, tenant_id)}, ip=ip,
    )
    await db.delete(tenant)
    await db.commit()
