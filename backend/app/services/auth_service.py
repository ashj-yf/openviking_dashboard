"""认证领域服务：登录校验、令牌签发、改密与首个管理员引导。"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import DashboardUser


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
    """用户自助改密：校验旧密码、禁止新旧相同，成功后解除 must_change_password。"""
    if not verify_password(old_password, user.password_hash):
        raise ValueError("旧密码不正确")
    if new_password == old_password:
        raise ValueError("新密码不能与旧密码相同")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await db.commit()


async def ensure_first_admin(db: AsyncSession, settings: Settings) -> None:
    """用户表为空时按配置创建首个平台管理员；表非空则 no-op（幂等）。"""
    count = await db.scalar(select(func.count()).select_from(DashboardUser))
    if count:
        return
    admin = DashboardUser(
        username=settings.first_admin_username,
        password_hash=hash_password(settings.first_admin_password),
        role="admin",
        is_active=True,
        must_change_password=True,
    )
    db.add(admin)
    await db.commit()
