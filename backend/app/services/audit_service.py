"""审计日志：写入自提交且不向调用方抛异常；查询按角色范围分页。"""
import json
import logging
from datetime import datetime, timezone
from typing import cast

from sqlalchemy import func, select
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


def parse_detail(raw: str | None) -> dict | None:
    """容错解析 detail_json：坏 JSON 或非 dict 内容降级为 {"_raw": 原串}，不得 500。"""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


async def list_logs(
    db: AsyncSession,
    *,
    actor: DashboardUser,
    action: str | None = None,
    actor_name: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AuditLog], int]:
    """按角色范围与筛选条件分页查询审计日志，返回 (本页行, 总数)。

    - admin 见全部；其余角色（team_admin）仅见本团队 actor 的行——
      actor_user_id 子查询限定（不用 join，避免 FK SET NULL 行为产生歧义），
      actor 被删除后该行随之不可见，属预期行为；
    - created_at 降序、id 兜底排序。
    """
    conditions = []
    # tz-aware 参数归一到 UTC naive 后再比较（DB 存 naive UTC）；naive 参数原样
    if start is not None and start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    if end is not None and end.tzinfo is not None:
        end = end.astimezone(timezone.utc).replace(tzinfo=None)
    # autoescape：用户输入中的 % / _ 按字面匹配，不作为 LIKE 通配符
    if action:
        conditions.append(AuditLog.action.startswith(action, autoescape=True))
    if actor_name:
        conditions.append(AuditLog.actor_name.contains(actor_name, autoescape=True))
    if start is not None:
        conditions.append(AuditLog.created_at >= start)
    if end is not None:
        conditions.append(AuditLog.created_at <= end)
    if actor.role != "admin":
        conditions.append(
            AuditLog.actor_user_id.in_(
                select(DashboardUser.id).where(
                    DashboardUser.tenant_id == actor.tenant_id
                )
            )
        )

    # count(*) 聚合恒返回一行，scalar 的 None 分支不可达
    total = cast(
        int,
        await db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)),
    )
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), total
