"""我的凭证路由：打码读取、显式显示/复制（审计）、自助重签。"""
from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DBSession, OVAdminDep
from app.schemas.credential import CredentialView, RevealedKeyOut
from app.schemas.user import KeyRegenerateRequest
from app.services import credential_service

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=CredentialView)
async def get_credentials(db: DBSession, current: CurrentUser):
    return await credential_service.get_view(db, current)


@router.post("/reveal", response_model=RevealedKeyOut)
async def reveal_key(request: Request, db: DBSession, current: CurrentUser):
    ip = request.client.host if request.client else None
    return await credential_service.expose(db, current, "key.view", ip)


@router.post("/copy", response_model=RevealedKeyOut)
async def copy_key(request: Request, db: DBSession, current: CurrentUser):
    ip = request.client.host if request.client else None
    return await credential_service.expose(db, current, "key.copy", ip)


@router.post("/regenerate", response_model=RevealedKeyOut)
async def regenerate_own_key(
    payload: KeyRegenerateRequest, request: Request,
    db: DBSession, ov: OVAdminDep, current: CurrentUser,
):
    ip = request.client.host if request.client else None
    return await credential_service.regenerate_self(db, ov, current, payload.seed, ip)
