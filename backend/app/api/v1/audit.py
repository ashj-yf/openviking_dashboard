"""审计日志查询路由（admin/team_admin 可见，范围随角色收窄）。"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from app.core.deps import AdminUser, DBSession, ManagerUser, OVSystemDep
from app.schemas.audit import AuditLogOut, AuditLogPageOut
from app.services import audit_service
from app.services.audit_service import parse_detail

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogPageOut)
async def list_audit_logs(
    db: DBSession,
    actor: ManagerUser,
    action: str | None = None,
    actor_name: str | None = Query(None, alias="actor"),
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AuditLogPageOut:
    rows, total = await audit_service.list_logs(
        db,
        actor=actor,
        action=action,
        actor_name=actor_name,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )
    return AuditLogPageOut(
        items=[
            AuditLogOut(
                id=row.id,
                actor_user_id=row.actor_user_id,
                actor_name=row.actor_name,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                detail=parse_detail(row.detail_json),
                ip=row.ip,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/ov")
async def list_ov_audit_logs(_: AdminUser, ov: OVSystemDep) -> Any:
    """透传 OV /console/audit（字段待真机抓包固化，Q12）。错误冒泡走全局 OpenVikingError handler。"""
    return await ov.console_audit()
