"""OpenViking account（租户）本地缓存与账户管理员密钥保管。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # 账户管理员 api_key 的 Fernet 密文；用于代理数据面 API
    admin_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ov_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    users: Mapped[list["OvUser"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="selectin"
    )


class OvUser(Base):
    """租户下 OpenViking 用户的本地映射/缓存。"""

    __tablename__ = "ov_users"
    __table_args__ = (UniqueConstraint("tenant_id", "ov_user_id", name="uq_tenant_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE")
    )
    ov_user_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(32), default="user")  # admin / user
    user_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
