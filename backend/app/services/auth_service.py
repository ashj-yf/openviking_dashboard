"""认证领域服务：登录校验、令牌签发、改密与超管账号启动同步。"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConfigError, Settings, get_settings, is_env_admin
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import DashboardUser
from app.schemas.auth import LoginResponse
from app.services.ldap_service import (
    LdapError,
    LdapUnavailableError,
    ldap_authenticate,
    ldap_mode_enabled,
)
from app.services import audit_service

logger = logging.getLogger("app.auth")

# bind_token 用途声明：与登录令牌互不通用（decode 侧强校验）
_BIND_TOKEN_PURPOSE = "ldap_bind"

_UNAUTHORIZED = (status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
_LDAP_UNAVAILABLE = (status.HTTP_503_SERVICE_UNAVAILABLE, "LDAP 服务不可用，请联系管理员")


async def authenticate(
    db: AsyncSession, username: str, password: str
) -> DashboardUser | None:
    """用户名密码校验。用户不存在、已停用、密码错误统一返回 None，不区分原因。"""
    user = (
        await db.scalars(
            select(DashboardUser).where(DashboardUser.username == username)
        )
    ).first()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return user


def issue_token(user: DashboardUser) -> str:
    """签发 JWT；claims 仅含 sub/username/role（iat/exp 由 security 层补充）。"""
    return create_access_token(
        str(user.id),
        {"username": user.username, "role": user.role},
    )


def issue_bind_token(user_id: int, minutes: int = 5) -> str:
    """签发绑定专用短时令牌（默认 5 分钟）；purpose=ldap_bind 与登录令牌互不通用。"""
    return create_access_token(str(user_id), {"purpose": _BIND_TOKEN_PURPOSE}, minutes=minutes)


def decode_bind_token(token: str) -> int:
    """校验绑定令牌并返回用户 id；用途不符抛 ValueError（路由映射 401）。"""
    payload = decode_access_token(token)
    if payload.get("purpose") != _BIND_TOKEN_PURPOSE:
        raise ValueError("令牌用途不符")
    return int(payload["sub"])


async def _login_success(
    db: AsyncSession, settings: Settings, user: DashboardUser, ip: str | None
) -> LoginResponse:
    """登录成功收尾：更新 last_login、审计并发正式 token。"""
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await audit_service.record(db, "auth.login.success", actor=user, ip=ip)
    return LoginResponse(
        access_token=issue_token(user),
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        role=user.role,
    )


async def _login_reject(
    db: AsyncSession, username: str, ip: str | None
) -> HTTPException:
    """统一登录失败：防枚举文案 + 审计留痕，供各分流分支复用。"""
    await audit_service.record(
        db,
        "auth.login.fail",
        actor_name=username,
        detail={"username": username},
        ip=ip,
    )
    return HTTPException(*_UNAUTHORIZED)


async def login(
    db: AsyncSession,
    settings: Settings,
    username: str,
    password: str,
    *,
    ip: str | None,
) -> LoginResponse:
    """登录编排与分流（03 B3）；业务失败直接抛 HTTPException，路由只做 HTTP 映射。

    分流顺序：查用户 → 停用拦截（不触 LDAP）→ 超管恒本地 bcrypt → LDAP 模式
    （未知用户 JIT 建档 / 已绑定走 LDAP 验密 / 未绑定本地口令通过后引导绑定）
    → 本地模式既有 authenticate 路径。
    """
    user = (
        await db.scalars(
            select(DashboardUser).where(DashboardUser.username == username)
        )
    ).first()

    # 停用一律拒绝且不触 LDAP：避免停用账号借 LDAP 目录验密绕过
    if user is not None and not user.is_active:
        raise await _login_reject(db, username, ip)

    # 超管（env 配置）恒本地 bcrypt，不参与 LDAP 分流
    if user is not None and is_env_admin(settings, user.username):
        if not verify_password(password, user.password_hash):
            raise await _login_reject(db, username, ip)
        return await _login_success(db, settings, user, ip)

    if await ldap_mode_enabled(db):
        if user is None:
            # 未知用户：LDAP 验密通过则 JIT 建档（role=user、tenant/ov 全空）
            try:
                user_dn, attrs = await ldap_authenticate(db, username, password)
            except LdapUnavailableError as exc:
                raise HTTPException(*_LDAP_UNAVAILABLE) from exc
            except LdapError as exc:
                raise await _login_reject(db, username, ip) from exc
            uid = attrs.get("uid") or username
            if is_env_admin(settings, uid):
                # 与超管账号名冲突：拒绝 JIT，防止借目录同名条目夺取超管
                await audit_service.record(
                    db,
                    "auth.ldap.jit_rejected",
                    actor_name=username,
                    detail={"username": username, "reason": "env_admin_name_conflict"},
                    ip=ip,
                )
                raise HTTPException(*_UNAUTHORIZED)
            user = DashboardUser(
                username=uid,
                role="user",
                auth_source="ldap",
                ldap_username=uid,
                ldap_dn=user_dn,
                bound_at=datetime.now(timezone.utc),
                is_active=True,
                must_change_password=False,
            )
            db.add(user)
            await db.commit()
            await audit_service.record(
                db,
                "auth.ldap.jit_create",
                actor=user,
                detail={"username": uid, "ldap_dn": user_dn},
                ip=ip,
            )
            return await _login_success(db, settings, user, ip)

        if user.auth_source == "ldap":
            # 已绑定用户：LDAP 验密，本地口令已作废
            try:
                await ldap_authenticate(db, user.ldap_username or username, password)
            except LdapUnavailableError as exc:
                raise HTTPException(*_LDAP_UNAVAILABLE) from exc
            except LdapError as exc:
                raise await _login_reject(db, username, ip) from exc
            return await _login_success(db, settings, user, ip)

        # 未绑定本地用户：本地口令通过则引导绑定（不发正式 token、不更 last_login）
        if verify_password(password, user.password_hash):
            return LoginResponse(
                role=user.role,
                must_bind=True,
                bind_token=issue_bind_token(user.id),
            )
        raise await _login_reject(db, username, ip)

    # 本地模式：既有统一校验路径（LDAP 绑定用户本地口令已空，一并判否）
    authed = await authenticate(db, username, password)
    if authed is None:
        raise await _login_reject(db, username, ip)
    return await _login_success(db, settings, authed, ip)


async def bind_ldap(
    db: AsyncSession,
    settings: Settings,
    user: DashboardUser,
    ldap_username: str,
    ldap_password: str,
    *,
    ip: str | None,
) -> None:
    """本地账号绑定 LDAP 身份并迁移为 LDAP 认证（03 B3）。

    守卫：已绑定 409 / 超管 403 / LDAP 用户名被他人占用 409；LDAP 验密失败
    400（审计 bind.fail）；服务不可用 503。成功写四个绑定字段、清空本地口令
    并提交，随后审计 bind.success。
    """
    if user.auth_source == "ldap":
        raise HTTPException(status.HTTP_409_CONFLICT, "该账号已绑定 LDAP")
    if is_env_admin(settings, user.username):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "超管账号不支持绑定 LDAP")
    taken = (
        await db.scalars(
            select(DashboardUser).where(
                DashboardUser.ldap_username == ldap_username,
                DashboardUser.id != user.id,
            )
        )
    ).first()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该 LDAP 账号已被其他用户绑定")
    try:
        user_dn, _attrs = await ldap_authenticate(db, ldap_username, ldap_password)
    except LdapUnavailableError as exc:
        raise HTTPException(*_LDAP_UNAVAILABLE) from exc
    except LdapError as exc:
        await audit_service.record(
            db,
            "auth.ldap.bind.fail",
            actor=user,
            detail={"ldap_username": ldap_username},
            ip=ip,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "LDAP 账号或密码错误") from exc
    user.auth_source = "ldap"
    user.ldap_username = ldap_username
    user.ldap_dn = user_dn
    user.bound_at = datetime.now(timezone.utc)
    user.password_hash = None
    await db.commit()
    await audit_service.record(
        db,
        "auth.ldap.bind.success",
        actor=user,
        detail={"ldap_username": ldap_username},
        ip=ip,
    )


async def change_password(
    db: AsyncSession,
    user: DashboardUser,
    old_password: str,
    new_password: str,
) -> None:
    """用户自助改密：校验旧密码、禁止新旧相同，成功后解除 must_change_password。

    超管账号（env 配置）UI 禁改密：密码仅可经 .env 轮换后重启生效（01 AUTH-3）；
    LDAP 用户密码由目录统一管理，看板不受理改密。
    """
    if is_env_admin(get_settings(), user.username):
        raise ValueError("超管账号密码仅可通过 .env 配置修改，重启服务后生效")
    if user.auth_source == "ldap":
        raise ValueError("LDAP 用户密码由 LDAP 统一管理，无法在此修改")
    if not verify_password(old_password, user.password_hash):
        raise ValueError("旧密码不正确")
    if new_password == old_password:
        raise ValueError("新密码不能与旧密码相同")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await db.commit()


async def sync_first_admin(db: AsyncSession, settings: Settings) -> None:
    """按 .env 同步超管账密入库；env 未配置时要求库中存在可用 admin，否则拒绝启动。

    - env 成对配置：账号不存在则创建（role=admin、启用、不强制改密），已存在则
      强制刷新密码哈希并校准角色/启用位——.env 是超管账密的权威来源（01 AUTH-3）；
    - env 未配置：库中存在 role=admin 且 is_active=True 的账号即放行（按库认证）。
    """
    username = settings.first_admin_username.strip()
    if username and settings.first_admin_password.strip():
        password_hash = hash_password(settings.first_admin_password)
        user = (
            await db.scalars(
                select(DashboardUser).where(DashboardUser.username == username)
            )
        ).first()
        if user is None:
            db.add(
                DashboardUser(
                    username=username,
                    password_hash=password_hash,
                    role="admin",
                    is_active=True,
                    # UI 禁改超管密码，密码门禁不可置位（否则死锁）
                    must_change_password=False,
                )
            )
            await db.commit()
            logger.info("已按环境配置创建超管账号 %s", username)
        else:
            user.password_hash = password_hash
            user.role = "admin"
            user.is_active = True
            user.must_change_password = False
            await db.commit()
            logger.info("已按环境配置刷新超管账号 %s 的密码", username)
        return
    admins = await db.scalar(
        select(func.count())
        .select_from(DashboardUser)
        .where(DashboardUser.role == "admin", DashboardUser.is_active.is_(True))
    )
    if not admins:
        raise ConfigError(
            "FIRST_ADMIN_USERNAME / FIRST_ADMIN_PASSWORD 未配置，"
            "且数据库中不存在可用的管理员账号，拒绝启动"
        )
