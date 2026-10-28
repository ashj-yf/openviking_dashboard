"""审计日志写入：自提交、永不向调用方抛出异常。"""
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, DashboardUser

logger = logging.getLogger("app.audit")


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor: DashboardUser | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """写入一条审计日志并自行 commit；任何失败只记录日志，不向外抛。

    注意：detail 只应放业务上下文，绝不能包含密码、密钥等敏感材料。
    """
    try:
        resolved_name = (
            actor_name or getattr(actor, "username", None) or "anonymous"
        )
        entry = AuditLog(
            actor_user_id=getattr(actor, "id", None),
            actor_name=resolved_name,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail_json=(
                json.dumps(detail, ensure_ascii=False) if detail is not None else None
            ),
            ip=ip,
        )
        db.add(entry)
        await db.commit()
    except Exception:  # noqa: BLE001 - 审计失败不能影响主流程
        logger.error("审计日志写入失败: action=%s", action, exc_info=True)
