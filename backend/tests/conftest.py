"""pytest 全局夹具。环境变量必须在任何 app.* 模块导入前设置。"""
import json
import os
import pathlib
import secrets
import tempfile
from collections.abc import AsyncGenerator

_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="ovdash-test-"))
os.environ.update(
    {
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP_DIR / 'global.db'}",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "FIRST_ADMIN_USERNAME": "admin",
        "FIRST_ADMIN_PASSWORD": "Admin#12345",
        "OPENVIKING_ROOT_KEY": "test-root-key",
        "CORS_ORIGINS": "http://localhost:5173",
    }
)

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.crypto import encrypt_secret
from app.core.db import get_session
from app.core.security import hash_password
from app.main import create_app
from app.models import Base, DashboardUser, Tenant
from app.services.openviking.client import reset_test_transport, set_test_transport


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    from app.core.db import attach_sqlite_pragma
    attach_sqlite_pragma(eng)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest.fixture
def ov_mock():
    holder = {}
    set_test_transport(httpx.MockTransport(lambda req: holder["handler"](req)))
    yield holder
    reset_test_transport()


@pytest.fixture
def app(engine):
    application = create_app()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with factory() as session:
            yield session

    application.dependency_overrides[get_session] = _override_get_session
    return application


@pytest_asyncio.fixture
async def client(app, ov_mock):
    ov_mock["handler"] = lambda req: httpx.Response(200, json={"status": "ok"})
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest_asyncio.fixture
async def make_user(db):
    async def _factory(username: str, password: str, role: str, *,
                       tenant=None, tenant_id=None, ov_key=None, **kwargs):
        if tenant is not None:
            if isinstance(tenant, Tenant):
                tenant_id = tenant.id
            else:
                t = Tenant(**tenant)
                db.add(t)
                await db.flush()
                tenant_id = t.id
        user = DashboardUser(
            username=username,
            password_hash=hash_password(password),
            role=role,
            tenant_id=tenant_id,
            ov_user_key_encrypted=encrypt_secret(ov_key) if ov_key else None,
            **kwargs,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    return _factory


@pytest_asyncio.fixture
async def make_tenant(db):
    async def _factory(ov_account_id: str, **kwargs):
        tenant = Tenant(
            ov_account_id=ov_account_id,
            admin_user_id=kwargs.pop("admin_user_id", "boss"),
            **kwargs,
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        return tenant
    return _factory


@pytest.fixture
def ov_calls(ov_mock):
    """记录全部 OV 请求；responses 队列可预置 (status, json) 或 httpx.Response。"""
    calls: list[dict] = []
    responses: list = []

    def _handler(req):
        try:
            body = json.loads(req.content) if req.content else None
        except Exception:
            body = None
        calls.append({
            "method": req.method,
            "path": req.url.path,
            "body": body,
            "authorization": req.headers.get("authorization", ""),
        })
        if responses:
            item = responses.pop(0)
            return item if isinstance(item, httpx.Response) else httpx.Response(item[0], json=item[1])
        return httpx.Response(200, json={})

    ov_mock["handler"] = _handler
    return {"calls": calls, "responses": responses}


@pytest.fixture
def auth_headers():
    """直接为本机已存在用户签发 JWT 构造认证头（不走登录）。"""
    from app.services.auth_service import issue_token

    def _make(user) -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_token(user)}"}

    return _make
