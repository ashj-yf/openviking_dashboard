from fastapi import APIRouter, Depends, Request, status

from app.core.deps import CurrentAdmin, DBSession, OVAdminDep, get_tenant_or_404
from app.models import Tenant
from app.schemas.tenant import TenantCreate, TenantOut, TenantUpdate
from app.services import audit_service, tenant_service
from app.services.openviking.client import OpenVikingError

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _to_out(tenant: Tenant) -> TenantOut:
    return TenantOut(
        id=tenant.id,
        ov_account_id=tenant.ov_account_id,
        admin_user_id=tenant.admin_user_id,
        display_name=tenant.display_name,
        remark=tenant.remark,
        has_admin_key=bool(tenant.admin_key_encrypted),
        user_count=len(tenant.users),
        created_at=tenant.created_at,
        synced_at=tenant.synced_at,
    )


@router.get("", response_model=list[TenantOut])
async def list_tenants(db: DBSession, _: CurrentAdmin) -> list[TenantOut]:
    return [_to_out(t) for t in await tenant_service.list_tenants(db)]


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, request: Request, db: DBSession, admin_api: OVAdminDep, actor: CurrentAdmin
) -> TenantOut:
    if await tenant_service.get_tenant_by_account(db, payload.account_id):
        raise OpenVikingError(409, f"租户 {payload.account_id} 已存在")
    tenant = await tenant_service.create_tenant(db, payload, admin_api)
    await audit_service.record(
        db, actor, "tenant.create", target_type="tenant",
        target_id=payload.account_id, detail={"admin_user_id": payload.admin_user_id},
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_out(tenant)


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    db: DBSession, _: CurrentAdmin, tenant: Tenant = Depends(get_tenant_or_404)
) -> TenantOut:
    return _to_out(tenant)


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    payload: TenantUpdate,
    db: DBSession,
    _: CurrentAdmin,
    tenant: Tenant = Depends(get_tenant_or_404),
) -> TenantOut:
    return _to_out(await tenant_service.update_tenant(db, tenant, payload))


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    request: Request,
    db: DBSession,
    admin_api: OVAdminDep,
    actor: CurrentAdmin,
    tenant: Tenant = Depends(get_tenant_or_404),
) -> None:
    account_id = tenant.ov_account_id
    await tenant_service.delete_tenant(db, tenant, admin_api)
    await audit_service.record(
        db, actor, "tenant.delete", target_type="tenant", target_id=account_id,
        ip=request.client.host if request.client else None,
    )
    await db.commit()


@router.post("/{tenant_id}/sync-users", status_code=status.HTTP_200_OK)
async def sync_users(
    db: DBSession,
    admin_api: OVAdminDep,
    actor: CurrentAdmin,
    tenant: Tenant = Depends(get_tenant_or_404),
) -> dict:
    users = await tenant_service.sync_users(db, tenant, admin_api)
    return {"synced": len(users)}
