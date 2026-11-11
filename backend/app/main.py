"""OpenViking Dashboard 后端入口。"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.auth import router as auth_router
from app.api.v1.audit import router as audit_router
from app.api.v1.credentials import router as credentials_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.users import router as users_router
from app.core.config import ConfigError, get_settings, validate_settings
from app.core.db import SessionLocal, engine
from app.core.deps import DBSession
from app.core.migrations import apply_schema_upgrades
from app.models.base import Base
from app.schemas.health import HealthResponse
from app.services.auth_service import sync_first_admin
from app.services.health_service import get_health
from app.services.openviking.client import OpenVikingError

logger = logging.getLogger("app")

# 容器内前端静态产物固定路径（Dockerfile 多阶段构建把 vite dist COPY 到此处）。
# 本地开发通常没有该目录，此时不挂载静态托管，API 与本地 Vite 工作流不受影响。
STATIC_DIR = Path("/app/static")


class SPAStaticFiles(StaticFiles):
    """html=True 的 StaticFiles：GET/HEAD 未命中静态文件时回退 index.html。

    /api/* 与 /healthz 的 404 不回退（它们在路由表中先于本挂载注册，
    这里的判断仅用于兜住进入静态挂载的未知 /api/* 深链，确保返回 JSON 404）。
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD"):
                raise
            request_path = scope.get("path", "")
            if request_path == "/healthz" or request_path.startswith("/api/"):
                raise
            return await super().get_response("index.html", scope)


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
        # create_all 不会改动既有表，旧库的新增列/索引在这里增量补齐
        applied = await conn.run_sync(apply_schema_upgrades)
    if applied:
        logger.info("启动迁移已应用: %s", ", ".join(applied))
    async with SessionLocal() as db:
        try:
            await sync_first_admin(db, settings)
        except ConfigError as exc:
            logger.error("%s", exc)
            raise SystemExit(str(exc))
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

    @app.get("/healthz", tags=["system"], response_model=HealthResponse)
    async def healthz(db: DBSession) -> JSONResponse:
        body = await get_health(db)
        return JSONResponse(status_code=200 if body.db else 503, content=body.model_dump())

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(credentials_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")

    # 最后挂静态产物：路由按注册顺序匹配，/healthz、/api/v1/* 已先注册。
    if STATIC_DIR.is_dir():
        app.mount(
            "/",
            SPAStaticFiles(directory=str(STATIC_DIR), html=True),
            name="spa-static",
        )
    return app


app = create_app()
