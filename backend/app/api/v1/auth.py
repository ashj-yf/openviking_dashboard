from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.core.deps import CurrentAdmin, DBSession
from app.core.security import create_access_token
from app.schemas.auth import AdminUserOut, LoginRequest, TokenResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: DBSession) -> TokenResponse:
    user = await auth_service.authenticate(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    settings = get_settings()
    token = create_access_token(str(user.id), {"username": user.username})
    return TokenResponse(
        access_token=token, expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/me", response_model=AdminUserOut)
async def me(admin: CurrentAdmin) -> AdminUser:
    return admin
