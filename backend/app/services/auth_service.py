"""后台账号登录校验。"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models import AdminUser


async def authenticate(db: AsyncSession, username: str, password: str) -> AdminUser | None:
    user = await db.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return user


def issue_token(user: AdminUser) -> str:
    return create_access_token(str(user.id), {"username": user.username, "su": user.is_superuser})


async def ensure_default_admin(db: AsyncSession, username: str, password: str) -> None:
    exists = await db.scalar(select(AdminUser).where(AdminUser.username == username))
    if exists is None:
        db.add(
            AdminUser(
                username=username,
                password_hash=hash_password(password),
                is_superuser=True,
            )
        )
        await db.commit()
