"""api_key 签发记录。明文密钥不落库，仅留指纹与上下文用于审计。"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KeyRecord(Base, TimestampMixin):
    __tablename__ = "key_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    ov_user_id: Mapped[str] = mapped_column(String(128), index=True)
    # admin = 账户管理员密钥；user = 普通用户密钥
    key_kind: Mapped[str] = mapped_column(String(16), default="user")
    # 仅用于辨识的展示信息，如密钥前 8 位
    key_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seed_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id"), nullable=True
    )
