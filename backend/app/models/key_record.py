"""OpenViking user key 签发历史；只存 hint，不存明文。"""
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KeyRecord(Base, TimestampMixin):
    __tablename__ = "key_records"
    __table_args__ = (
        Index(
            "uq_key_record_current",
            "dashboard_user_id",
            unique=True,
            sqlite_where=sql_text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    dashboard_user_id: Mapped[int] = mapped_column(
        ForeignKey("dashboard_users.id", ondelete="CASCADE"), index=True
    )
    ov_user_id: Mapped[str] = mapped_column(String(128))
    # admin（team_admin 留存的账户管理员 key）/ user
    key_kind: Mapped[str] = mapped_column(String(16))
    key_hint: Mapped[str] = mapped_column(String(32))
    seed_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[int | None] = mapped_column(
        ForeignKey("dashboard_users.id", ondelete="SET NULL"), nullable=True
    )
