"""审计日志写入与查询。"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminUser, AuditLog


async def record(
    db: AsyncSession,
    actor: AdminUser | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    log = AuditLog(
        admin_user_id=actor.id if actor else None,
        actor_name=actor.username if actor else "anonymous",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        ip=ip,
    )
    db.add(log)
    await db.flush()
    return log


async def list_logs(
    db: AsyncSession, *, page: int = 1, page_size: int = 20, action: str | None = None
) -> tuple[list[AuditLog], int]:
    from sqlalchemy import func

    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return list(rows), int(total or 0)
