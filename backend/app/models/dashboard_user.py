"""Dashboard 登录用户：平台管理员 / 账户管理员 / 普通用户三角色基线。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.tenant import Tenant


class DashboardUser(Base, TimestampMixin):
    __tablename__ = "dashboard_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ov_user_id", name="uq_tenant_ov_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # admin（平台管理员）/ team_admin（账户管理员）/ user
    role: Mapped[str] = mapped_column(String(16), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    ov_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ov_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ov_user_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant | None] = relationship(lazy="selectin")

    @property
    def account_id(self) -> str | None:
        """OpenViking 侧 account_id，来自绑定租户。"""
        return self.tenant.ov_account_id if self.tenant is not None else None

    @property
    def has_ov_key(self) -> bool:
        """仅暴露 OV user key 是否留存，绝不返回密文本身。"""
        return bool(self.ov_user_key_encrypted)
