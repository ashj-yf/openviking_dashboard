"""OpenViking account（租户）本地缓存。"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # OpenViking 侧的 account_id
    ov_account_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # 创建账户时指定的该账户初始管理员 user_id
    admin_user_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
