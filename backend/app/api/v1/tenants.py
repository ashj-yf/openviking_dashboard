"""团队管理路由（平台 admin 专属）。"""
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.deps import AdminUser, DBSession, OVAdminDep
from app.schemas.tenant import (
    TenantCreatedOut,
    TenantCreateRequest,
    TenantDeleteRequest,
    TenantDetailOut,
    TenantListItem,
    TenantSyncReport,
    TenantUpdateRequest,
)
from app.services import audit_service, tenant_service

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("")
async def list_tenants(db: DBSession, _: AdminUser, q: str | None = None):
    rows = await tenant_service.list_tenants(db, q)
    return [
        TenantListItem(
            id=t.id,
            account_id=t.ov_account_id,
            display_name=t.display_name,
            remark=t.remark,
            admin_user_id=t.admin_user_id,
            user_count=count,
            synced_at=t.synced_at,
            created_at=t.created_at,
        )
        for t, count in rows
    ]


@router.get("/{tenant_id}", response_model=TenantDetailOut)
async def get_tenant(tenant_id: int, db: DBSession, ov: OVAdminDep, _: AdminUser):
    detail = await tenant_service.get_detail(db, ov, tenant_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")
    return detail


@router.patch("/{tenant_id}", response_model=TenantListItem)
async def update_tenant(
    tenant_id: int,
    payload: TenantUpdateRequest,
    request: Request,
    db: DBSession,
    admin: AdminUser,
):
    tenant = await tenant_service.update_local(
        db, tenant_id, payload.display_name, payload.remark
    )
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")
    count = await tenant_service.user_count(db, tenant_id)
    await audit_service.record(
        db, "tenant.update", actor=admin, target_type="tenant",
        target_id=tenant.ov_account_id, ip=request.client.host if request.client else None,
    )
    return TenantListItem(
        id=tenant.id, account_id=tenant.ov_account_id, display_name=tenant.display_name,
        remark=tenant.remark, admin_user_id=tenant.admin_user_id, user_count=count,
        synced_at=tenant.synced_at, created_at=tenant.created_at,
    )


@router.post("/{tenant_id}/sync", response_model=TenantSyncReport)
async def sync_tenant(
    tenant_id: int, request: Request, db: DBSession, ov: OVAdminDep, admin: AdminUser
):
    tenant = await tenant_service.get_raw(db, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "团队不存在")
    report = await tenant_service.sync_users(db, ov, tenant)
    await audit_service.record(
        db, "tenant.sync", actor=admin, target_type="tenant",
        target_id=tenant.ov_account_id,
        detail={"ov_user_count": report.ov_user_count,
                "local_user_count": report.local_user_count,
                "matched": report.matched,
                "missing_local": len(report.missing_local),
                "extra_local": len(report.extra_local)},
        ip=request.client.host if request.client else None,
    )
    return report


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantCreatedOut)
async def create_tenant(
    payload: TenantCreateRequest,
    request: Request,
    db: DBSession,
    ov: OVAdminDep,
    admin: AdminUser,
):
    ip = request.client.host if request.client else None
    return await tenant_service.create_tenant(db, ov, admin, payload, ip=ip)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: int,
    payload: TenantDeleteRequest,
    request: Request,
    db: DBSession,
    ov: OVAdminDep,
    admin: AdminUser,
):
    ip = request.client.host if request.client else None
    await tenant_service.delete_tenant(
        db, ov, tenant_id, confirm=payload.confirm, actor=admin, ip=ip
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
