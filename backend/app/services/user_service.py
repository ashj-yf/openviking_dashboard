"""用户领域逻辑：范围守卫、开通、角色/启停用/重置/销户/重签/同步。"""
import logging
from datetime import datetime, timezone
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.core.security import hash_password
from app.models import DashboardUser, KeyRecord, Tenant
from app.schemas.user import UserCreateRequest
from app.services import audit_service
from app.services.openviking.client import OpenVikingError
from app.services.openviking.payloads import extract_user_key

logger = logging.getLogger("app.user")

OV_ROLE_BY_DASHBOARD = {"team_admin": "admin", "user": "user"}


async def assert_can_manage(actor: DashboardUser, target: DashboardUser) -> None:
    """team_admin 仅能管理本团队普通成员；平台 admin 放行；其余 403。"""
    if actor.role == "admin":
        return
    if actor.role == "team_admin":
        if target.tenant_id != actor.tenant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只能管理本团队成员")
        if target.role == "team_admin":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "团队管理员席位仅平台管理员可操作"
            )
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "无用户管理权限")


async def get_target_or_404(db: AsyncSession, user_id: int) -> DashboardUser:
    target = await db.get(DashboardUser, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return target


async def list_users(
    db: AsyncSession,
    actor: DashboardUser,
    *,
    tenant_id: int | None = None,
    keyword: str | None = None,
) -> list[DashboardUser]:
    stmt = select(DashboardUser)
    if actor.role == "team_admin":
        stmt = stmt.where(DashboardUser.tenant_id == actor.tenant_id)
    elif tenant_id is not None:
        stmt = stmt.where(DashboardUser.tenant_id == tenant_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(DashboardUser.username.ilike(like), DashboardUser.ov_user_id.ilike(like))
        )
    stmt = stmt.order_by(DashboardUser.id)
    return list((await db.scalars(stmt)).all())


async def current_key_record(db: AsyncSession, user_id: int) -> KeyRecord | None:
    return (
        await db.scalars(
            select(KeyRecord).where(
                KeyRecord.dashboard_user_id == user_id, KeyRecord.is_current.is_(True)
            )
        )
    ).first()


async def create_user(
    db: AsyncSession,
    admin_api,
    actor: DashboardUser,
    payload: UserCreateRequest,
    *,
    ip: str | None,
) -> DashboardUser:
    # 角色与归属决策
    if actor.role == "team_admin":
        if payload.role != "user":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "团队管理员只能开通普通成员"
            )
        tenant_id = actor.tenant_id
    else:
        if not payload.tenant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请选择归属团队")
        tenant_id = payload.tenant_id

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")

    if (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == payload.username)
    )).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "登录名已存在")

    ov_user_id = payload.ov_user_id or payload.username
    if (await db.scalars(
        select(DashboardUser).where(
            DashboardUser.tenant_id == tenant_id,
            DashboardUser.ov_user_id == ov_user_id,
        )
    )).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "团队内 ov_user_id 已存在")

    ov_role = OV_ROLE_BY_DASHBOARD[payload.role]
    # 先 OV 注册；OpenVikingError 交全局处理器透传，本地零写入
    register_resp = await admin_api.register_user(
        tenant.ov_account_id, ov_user_id, role=ov_role, seed=payload.seed
    )
    new_key = extract_user_key(register_resp)

    # 注册成功即落本地映射，保证 OV 用户可被追踪；签发完成前不激活
    user = DashboardUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=False,
        tenant_id=tenant_id,
        ov_user_id=ov_user_id,
        ov_role=ov_role,
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if new_key is None:
        try:
            key_resp = await admin_api.regenerate_key(
                tenant.ov_account_id, ov_user_id, seed=payload.seed
            )
            new_key = extract_user_key(key_resp)
        except OpenVikingError as exc:
            await _provision_failed(db, actor, user, exc, ip)

    if not new_key:
        await _provision_failed(
            db, actor, user,
            OpenVikingError(502, "OpenViking 响应中未找到 key 字段", "/key"),
            ip,
        )

    await _store_fresh_key(
        db, user, new_key, seed_used=payload.seed is not None, issued_by=actor.id
    )
    user.is_active = True
    await db.commit()
    # 新建对象未经 select，tenant 关系尚未按 selectin 加载；路由要构造 UserOut，必须 refresh
    await db.refresh(user)
    await audit_service.record(
        db, "user.create", actor=actor, target_type="dashboard_user",
        target_id=str(user.id),
        detail={"tenant": tenant.ov_account_id, "ov_user_id": ov_user_id,
                "role": payload.role, "seed_used": payload.seed is not None},
        ip=ip,
    )
    return user


async def _provision_failed(db, actor, user, exc: OpenVikingError, ip) -> NoReturn:
    logger.error(
        "OV 用户已创建但 key 签发失败 user=%s status=%s", user.username, exc.status_code
    )
    await audit_service.record(
        db, "user.key.issue_failed", actor=actor, target_type="dashboard_user",
        target_id=str(user.id), detail={"ov_user_id": user.ov_user_id}, ip=ip,
    )
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        {
            "message": "OpenViking 用户已创建但密钥签发失败，请稍后重试签发",
            "user_id": user.id,
        },
    )


async def _store_fresh_key(
    db: AsyncSession, user: DashboardUser, plain_key: str, *,
    seed_used: bool, issued_by: int | None,
) -> None:
    """覆盖密文并翻转 current 记录；调用方负责 commit。"""
    current = await current_key_record(db, user.id)
    if current is not None:
        current.is_current = False
    user.ov_user_key_encrypted = encrypt_secret(plain_key)
    user.key_synced_at = datetime.now(timezone.utc)
    db.add(KeyRecord(
        tenant_id=user.tenant_id,
        dashboard_user_id=user.id,
        ov_user_id=user.ov_user_id,
        key_kind="admin" if user.ov_role == "admin" else "user",
        key_hint=plain_key[:8],
        seed_used=seed_used,
        is_current=True,
        issued_by=issued_by,
    ))
    await db.flush()
