"""Dashboard 登录用户：平台管理员 / 账户管理员 / 普通用户三角色基线。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.tenant import Tenant


class DashboardUser(Base, TimestampMixin):
    __tablename__ = "dashboard_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ov_user_id", name="uq_tenant_ov_user"),
        Index("uq_dashboard_users_ldap_username", "ldap_username", unique=True),
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
    # 认证来源：local（本机密码）/ ldap
    auth_source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="local", server_default="local"
    )
    # LDAP 绑定信息：绑定的 LDAP 用户名 / 完整 DN / 绑定时间，未绑定时为空
    ldap_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ldap_dn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped[Tenant | None] = relationship(lazy="selectin")
