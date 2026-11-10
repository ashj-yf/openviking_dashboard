"""认证领域服务：登录校验、令牌签发、改密与超管账号启动同步。"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConfigError, Settings, get_settings, is_env_admin
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import DashboardUser

logger = logging.getLogger("app.auth")


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


async def change_password(
    db: AsyncSession,
    user: DashboardUser,
    old_password: str,
    new_password: str,
) -> None:
    """用户自助改密：校验旧密码、禁止新旧相同，成功后解除 must_change_password。

    超管账号（env 配置）UI 禁改密：密码仅可经 .env 轮换后重启生效（01 AUTH-3）。
    """
    if is_env_admin(get_settings(), user.username):
        raise ValueError("超管账号密码仅可通过 .env 配置修改，重启服务后生效")
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
