"""OpenViking Dashboard 后端入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.auth import admin_users_router, router as auth_router
from app.core.config import ConfigError, get_settings, validate_settings
from app.core.db import SessionLocal, engine
from app.core.deps import DBSession
from app.models.base import Base
from app.services.auth_service import ensure_first_admin
from app.services.health_service import get_health
from app.services.openviking.client import OpenVikingError

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        validate_settings(settings)
    except ConfigError as exc:
        logger.error("%s", exc)
        raise SystemExit(str(exc))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await ensure_first_admin(db, settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(OpenVikingError)
    async def _ov_error_handler(_: Request, exc: OpenVikingError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "ov_status": exc.status_code},
        )

    @app.get("/healthz", tags=["system"])
    async def healthz(db: DBSession) -> JSONResponse:
        body = await get_health(db)
        return JSONResponse(status_code=200 if body.db else 503, content=body.model_dump())

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(admin_users_router, prefix="/api/v1")
    return app


app = create_app()
