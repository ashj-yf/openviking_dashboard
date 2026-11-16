"""用户领域逻辑：范围守卫、开通、角色/启停用/重置/销户/重签/同步。"""
import logging
from datetime import datetime, timezone
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, is_env_admin
from app.core.crypto import encrypt_secret
from app.core.security import hash_password
from app.models import DashboardUser, KeyRecord, Tenant
from app.schemas.user import UserCreateRequest, UserProvisionRequest, UserSyncReport
from app.services import audit_service
from app.services.ldap_service import ldap_mode_enabled
from app.services.openviking.client import OpenVikingError
from app.services.openviking.payloads import (
    extract_remote_role,
    extract_remote_user_id,
    extract_user_key,
    extract_users_list,
)

logger = logging.getLogger("app.user")

OV_ROLE_BY_DASHBOARD = {"team_admin": "admin", "user": "user"}


async def assert_can_manage(actor: DashboardUser, target: DashboardUser) -> None:
    """team_admin 仅能管理本团队普通成员；平台 admin 放行；其余 403。"""
    if actor.role == "admin":
        assert_not_env_admin(target)
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


def assert_not_env_admin(target: DashboardUser) -> None:
    """超管账号受环境配置保护：UI 一切修改入口拒绝（01 AUTH-3）。

    该断言针对 target 的用户名判定，与操作者无关——任何人（含其他 admin）
    都不能在界面修改超管账号。
    """
    if is_env_admin(get_settings(), target.username):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "超管账号受环境配置保护，无法在界面修改",
        )


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
    # LDAP 模式封锁本机建档入口：新用户一律经 LDAP 登录 JIT 自动建档（B4）
    if await ldap_mode_enabled(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "LDAP 模式下禁止创建用户，新用户请直接 LDAP 登录自动建档",
        )
    # 超管用户名保留给 env 同步，不可经用户管理创建同名账号（防冒充/混淆）
    if is_env_admin(get_settings(), payload.username):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "该用户名为环境配置的超管账号，不可重复创建",
        )
    # 登录名唯一检查前置到分叉之前：无团队本地账号与团队开通两条路径共用
    if (await db.scalars(
        select(DashboardUser).where(DashboardUser.username == payload.username)
    )).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "登录名已存在")

    # 角色与归属决策
    if actor.role == "team_admin":
        if payload.role != "user":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "团队管理员只能开通普通成员"
            )
        tenant_id = actor.tenant_id
    else:
        if payload.role == "team_admin" and not payload.tenant_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "未选择团队时角色只能为普通用户"
            )
        if not payload.tenant_id:
            # 无团队：落可登录的未开通本地账号，不触 OV；
            # 显式传入的 ov_user_id/seed 在此分支被忽略（开通时再定）
            return await _create_local_unprovisioned(db, actor, payload, ip=ip)
        tenant_id = payload.tenant_id

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")

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

    new_key = await _issue_initial_key(
        db, admin_api, actor, user,
        register_resp=register_resp, tenant=tenant, ov_user_id=ov_user_id,
        seed=payload.seed, ip=ip,
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


async def _create_local_unprovisioned(
    db: AsyncSession,
    actor: DashboardUser,
    payload: UserCreateRequest,
    *,
    ip: str | None,
) -> DashboardUser:
    """无团队路径：落可登录但未开通 OV 的本地账号（两段式开通的前半段）。

    登录名唯一检查已在 create_user 分叉前完成，无需重复；tenant/ov 字段
    全空，开通（后续任务）时再定归属与 OV 身份。
    """
    user = DashboardUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit_service.record(
        db, "user.create", actor=actor, target_type="dashboard_user",
        target_id=str(user.id),
        detail={"unprovisioned": True, "role": "user"},
        ip=ip,
    )
    return user


async def provision_jit_user(
    db: AsyncSession,
    admin_api,
    actor: DashboardUser,
    target: DashboardUser,
    payload: UserProvisionRequest,
    *,
    ip: str | None,
) -> DashboardUser:
    """未开通用户开通（LDAP JIT / 本地预建）：补全团队归属并注册 OV、签发 key。

    仅平台 admin 可操作；复用 create_user 的 OV 先行顺序——注册失败
    OpenVikingError 透传，本地零写入；注册成功即落半成品（停用且无密文，
    保留 OV 归属），签发失败经 regenerate-key 可复活补救；签发成功则
    激活并审计 user.provision。
    """
    if actor.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅平台管理员可执行开通操作")
    if target.tenant_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户已开通")
    tenant = await db.get(Tenant, payload.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")
    ov_user_id = payload.ov_user_id or target.username
    if (await db.scalars(
        select(DashboardUser).where(
            DashboardUser.tenant_id == tenant.id,
            DashboardUser.ov_user_id == ov_user_id,
        )
    )).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "团队内 ov_user_id 已存在")

    ov_role = OV_ROLE_BY_DASHBOARD[payload.role]
    # OV 先行：注册失败透传 OpenVikingError，本地零写入
    register_resp = await admin_api.register_user(
        tenant.ov_account_id, ov_user_id, role=ov_role, seed=payload.seed
    )

    # 注册成功即落本地归属，对齐 create_user 半成品不变量（停用且无密文）：
    # 签发失败时保留 OV 归属，admin 可经 regenerate-key 复活补救（B4-R1）；
    # is_active=False 在登录侧被 AUTH-1 停用拦截（不触 LDAP 凭据校验）
    target.tenant_id = tenant.id
    target.role = payload.role
    target.ov_role = ov_role
    target.ov_user_id = ov_user_id
    # 仅 LDAP JIT 置 False；local 预建用户保留创建时的 True（首登改密语义）
    if target.auth_source == "ldap":
        target.must_change_password = False
    target.is_active = False
    await db.commit()
    await db.refresh(target)

    new_key = await _issue_initial_key(
        db, admin_api, actor, target,
        register_resp=register_resp, tenant=tenant, ov_user_id=ov_user_id,
        seed=payload.seed, ip=ip,
    )
    await _store_fresh_key(
        db, target, new_key, seed_used=payload.seed is not None, issued_by=actor.id
    )
    # 签发完成即恢复启用：半成品仅存在于签发失败的窗口期
    target.is_active = True
    await db.commit()
    # 行已被外部创建，tenant 关系未必按 selectin 加载；路由要构造 UserOut，必须 refresh
    await db.refresh(target)
    await audit_service.record(
        db, "user.provision", actor=actor, target_type="dashboard_user",
        target_id=str(target.id),
        detail={"tenant": tenant.ov_account_id, "ov_user_id": ov_user_id,
                "role": payload.role, "seed_used": payload.seed is not None},
        ip=ip,
    )
    return target


async def _issue_initial_key(
    db, admin_api, actor, user, *,
    register_resp, tenant: Tenant, ov_user_id: str, seed: str | None, ip,
) -> str:
    """注册响应优先取 key，缺失时向 OV 补签；失败审计后以 502 中断。

    create_user 与 provision_jit_user 共用：调用方保证 OV 注册已成功，
    key 到手之前本地不产生任何提交。
    """
    new_key = extract_user_key(register_resp)
    if new_key is None:
        try:
            key_resp = await admin_api.regenerate_key(
                tenant.ov_account_id, ov_user_id, seed=seed
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
    return new_key


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
            "ov_user_id": user.ov_user_id,
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


async def _last_active_platform_admin(db: AsyncSession, exclude_id: int | None = None) -> bool:
    stmt = select(func.count()).select_from(DashboardUser).where(
        DashboardUser.role == "admin", DashboardUser.is_active.is_(True)
    )
    if exclude_id is not None:
        stmt = stmt.where(DashboardUser.id != exclude_id)
    return (await db.scalar(stmt) or 0) == 0


async def _count_team_admins(db: AsyncSession, tenant_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(DashboardUser).where(
            DashboardUser.tenant_id == tenant_id,
            DashboardUser.role == "team_admin",
        )
    ) or 0


async def set_role(db, admin_api, actor, target: DashboardUser, new_role: str, *, ip):
    assert_not_env_admin(target)
    if actor.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能对自己执行角色变更")
    # JIT 未开通用户尚无 OV 身份，须先开通再调角色（B4）
    if target.auth_source == "ldap" and target.tenant_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该用户尚未开通，请先执行开通操作"
        )
    # 本地预建的未开通用户（无团队）同样须先开通；平台 admin 走下方 400 分支
    if target.tenant_id is None and target.role != "admin":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该用户尚未开通，请先执行开通操作"
        )
    if target.tenant_id is None or target.ov_user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "平台管理员没有 OpenViking 角色")
    if target.role == new_role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色未变更")
    if target.role == "team_admin" and new_role == "user":
        if await _count_team_admins(db, target.tenant_id) <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "团队最后一个团队管理员不可降级"
            )
    tenant = target.tenant
    # 先 OV，失败由全局处理器透传、本地不变
    await admin_api.set_role(
        tenant.ov_account_id, target.ov_user_id, OV_ROLE_BY_DASHBOARD[new_role]
    )
    target.role = new_role
    target.ov_role = OV_ROLE_BY_DASHBOARD[new_role]
    await db.commit()
    await audit_service.record(
        db, "user.role.change", actor=actor, target_type="dashboard_user",
        target_id=str(target.id), detail={"role": new_role}, ip=ip,
    )


async def reset_target_password(
    db, admin_api, actor, target: DashboardUser, new_password: str, *,
    regenerate: bool, seed: str | None, ip,
):
    assert_not_env_admin(target)
    # LDAP 用户口令由目录统一管理，本机重置入口封锁（B4）
    if target.auth_source == "ldap":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "LDAP 用户密码由 LDAP 统一管理，无法重置",
        )
    if regenerate:
        if target.tenant_id is None or target.ov_user_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "该账号没有 OpenViking key，无法联动重签"
            )
        await rotate_user_key(db, admin_api, actor, target, seed=seed, ip=ip)
    target.password_hash = hash_password(new_password)
    await db.commit()
    await audit_service.record(
        db, "user.password.reset", actor=actor, target_type="dashboard_user",
        target_id=str(target.id), detail={"regenerate_key": regenerate}, ip=ip,
    )


async def set_enabled(db, actor, target: DashboardUser, active: bool, *, ip):
    assert_not_env_admin(target)
    if actor.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能对自己执行该操作")
    if not active and target.role == "admin":
        if await _last_active_platform_admin(db, exclude_id=target.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "最后一个平台管理员不可禁用"
            )
    target.is_active = active
    await db.commit()
    await audit_service.record(
        db, "user.enable" if active else "user.disable", actor=actor,
        target_type="dashboard_user", target_id=str(target.id), ip=ip,
    )


async def rotate_user_key(
    db, admin_api, actor, target: DashboardUser, *, seed: str | None, ip,
    action: str = "user.key.regenerate",
) -> str:
    """管理员/服务内部重签：OV 成功后覆盖密文、翻转 record。

    仅激活"已注册但从未取到 key"的半成品（停用且 key 密文为空）；正常停用
    账号重签不改变启用位——密钥卫生操作不得复活被停用的账号（USER-5）。
    返回新明文。
    """
    assert_not_env_admin(target)
    if target.tenant_id is None or not target.ov_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账号没有 OpenViking 身份")
    tenant = target.tenant
    resp = await admin_api.regenerate_key(
        tenant.ov_account_id, target.ov_user_id, seed=seed
    )  # OpenVikingError 直接透传，本地不动
    new_key = extract_user_key(resp)
    if not new_key:
        raise OpenVikingError(
            502, "OpenViking 响应中未找到 key 字段",
            f"/api/v1/admin/accounts/{tenant.ov_account_id}/users/{target.ov_user_id}/key",
        )
    # 仅补救"已注册但从未取到 key"的半成品（停用且无密文）；正常停用账号重签不改变启用位（USER-5）
    # 判定必须先于 _store_fresh_key：该调用会把新密文写到同一属性上
    if not target.ov_user_key_encrypted:
        target.is_active = True
    await _store_fresh_key(
        db, target, new_key, seed_used=seed is not None, issued_by=actor.id if actor else None
    )
    await db.commit()
    await audit_service.record(
        db, action, actor=actor, target_type="dashboard_user",
        target_id=str(target.id), detail={"seed_used": seed is not None}, ip=ip,
    )
    return new_key


async def delete_user(db, admin_api, actor, target: DashboardUser, *, ip):
    assert_not_env_admin(target)
    if actor.id == target.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    if target.ov_user_id is None:
        # 本地无 OV 身份（JIT 未开通/平台管理员）：跳过 OV 删除与团队相关守卫（B4）
        if target.role == "admin" and target.tenant_id is None:
            # 保留平台管理员销户守卫与最后活跃平台 admin 保护
            if target.is_active and await _last_active_platform_admin(
                db, exclude_id=target.id
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "最后一个平台管理员不可删除"
                )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "平台管理员账号不支持销户"
            )
        await audit_service.record(
            db, "user.delete", actor=actor, target_type="dashboard_user",
            target_id=str(target.id),
            detail={"username": target.username},
            ip=ip,
        )
        await db.delete(target)
        await db.commit()
        return
    if target.tenant_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "平台管理员账号不支持销户")
    tenant = target.tenant
    if target.ov_user_id == tenant.admin_user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "账户初始管理员不可删除"
        )
    if target.role == "team_admin" and await _count_team_admins(db, target.tenant_id) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "团队最后一个团队管理员不可删除"
        )
    try:
        await admin_api.delete_user(tenant.ov_account_id, target.ov_user_id)
    except OpenVikingError:
        await audit_service.record(
            db, "user.delete.fail", actor=actor, target_type="dashboard_user",
            target_id=str(target.id),
            detail={"tenant": tenant.ov_account_id, "ov_user_id": target.ov_user_id},
            ip=ip,
        )
        raise
    await audit_service.record(
        db, "user.delete", actor=actor, target_type="dashboard_user",
        target_id=str(target.id),
        detail={"tenant": tenant.ov_account_id, "ov_user_id": target.ov_user_id,
                "username": target.username},
        ip=ip,
    )
    await db.delete(target)
    await db.commit()


async def sync_user(db, admin_api, target: DashboardUser):
    assert_not_env_admin(target)
    if target.tenant_id is None or not target.ov_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账号没有 OpenViking 身份")
    tenant = target.tenant
    payload = await admin_api.list_users(tenant.ov_account_id)
    remote: dict[str, str | None] = {}
    for u in extract_users_list(payload):
        uid = extract_remote_user_id(u)
        if uid:
            remote[uid] = extract_remote_role(u)
    ov_role = remote.get(target.ov_user_id)
    return UserSyncReport(
        account_id=tenant.ov_account_id,
        ov_user_id=target.ov_user_id,
        ov_exists=target.ov_user_id in remote,
        local_ov_role=target.ov_role,
        ov_role=ov_role,
        consistent=ov_role is not None and ov_role == target.ov_role,
    )
