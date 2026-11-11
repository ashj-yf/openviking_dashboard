"""LDAP 认证配置：纯 DB 单源，整表恒只有 id=1 一行。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LdapConfig(Base, TimestampMixin):
    __tablename__ = "ldap_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    server_host: Mapped[str] = mapped_column(String(256))
    server_port: Mapped[int] = mapped_column(Integer)
    # 加密方式：none / starttls / ldaps
    encryption: Mapped[str] = mapped_column(String(16))
    bind_dn: Mapped[str] = mapped_column(String(256))
    # Bind 密码 Fernet 密文，任何接口与日志不得回显明文
    bind_password_enc: Mapped[str] = mapped_column(Text)
    user_base_dn: Mapped[str] = mapped_column(String(256))
    # 用户搜索过滤器，如 (uid={username})
    user_filter: Mapped[str] = mapped_column(String(256))
    attr_uid: Mapped[str] = mapped_column(String(64), default="uid")
    attr_mail: Mapped[str] = mapped_column(String(64), default="mail")
    attr_display_name: Mapped[str] = mapped_column(String(64), default="displayName")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # 最近一次修改人，仅本机用户；删除后置空
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("dashboard_users.id", ondelete="SET NULL"), nullable=True
    )
