"""pytest 全局夹具。环境变量必须在任何 app.* 模块导入前设置。"""
import json
import os
import pathlib
import secrets
import tempfile
import warnings
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
from sqlalchemy import event
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
from starlette.exceptions import StarletteDeprecationWarning

# 收集期放行：pytest CLI -W error 不受 pyproject ini filterwarnings 约束，
# 而 starlette 1.10 在收集期 import test_static_spa.py 时就会发出 TestClient
# 弃用告警，导致收集直接报错。pytest 9 会在收集期的 catch_warnings 上下文里
# 把 CLI -W 过滤器重新压到过滤链最顶端，模块顶层的 filterwarnings 会被盖住，
# 因此必须挂在 pytest_collection 钩子里（钩子运行在应用 CLI 过滤器之后）；
# 测试执行期仍由 ini 的 ignore 规则管控。
warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)


@pytest.hookimpl
def pytest_collection() -> None:
    warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)


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
        # 夹具会话与 API 请求会话（见 app 夹具）是不同会话；SELECT 一律
        # populate_existing，避免身份映射中的夹具旧副本掩盖 API 侧已提交的变更。
        @event.listens_for(session.sync_session, "do_orm_execute")
        def _populate_existing(orm_execute_state) -> None:
            if (
                orm_execute_state.is_select
                and not orm_execute_state.is_column_load
                and not orm_execute_state.is_relationship_load
            ):
                orm_execute_state.statement = (
                    orm_execute_state.statement.execution_options(
                        populate_existing=True
                    )
                )

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
        # 未显式给出时按看板角色推导 OV 角色；平台 admin 无 OV 角色（None）
        kwargs.setdefault(
            "ov_role", {"team_admin": "admin", "user": "user"}.get(role)
        )
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


class FakeUser:
    """fake_ldap 的目录用户：DN、密码与展示属性。"""

    def __init__(self, dn: str, password: str, mail: str, display: str) -> None:
        self.dn = dn
        self.password = password
        self.mail = mail
        self.display = display


@pytest.fixture
def fake_ldap(monkeypatch):
    """LDAP 接缝假件：替换 ldap_service 两个同步接缝函数（B2/B3/B4 复用）。

    - users：用户名 -> FakeUser；fail_connect/fail_search/fail_verify 逐级注入失败；
    - search_calls/verify_calls 记录接缝调用，供测试断言两级 bind 的先后与参数。
    """
    from app.services import ldap_service

    class _Controller:
        def __init__(self) -> None:
            self.users: dict[str, FakeUser] = {}
            self.fail_connect = False
            self.fail_search = False
            self.fail_verify = False
            self.search_calls: list[dict] = []
            self.verify_calls: list[dict] = []

        def _search(self, cfg, username: str):
            self.search_calls.append({"username": username})
            if self.fail_connect:
                raise ldap_service.LdapUnavailableError("LDAP 服务不可用，请联系管理员")
            if self.fail_search:
                raise ldap_service.LdapError("search", "LDAP 用户搜索失败（fake）")
            user = self.users.get(username)
            if user is None:
                raise ldap_service.LdapError("search", "未在 LDAP 中找到该用户（fake）")
            return user.dn, {
                "uid": username,
                "mail": user.mail,
                "display_name": user.display,
            }

        def _verify(self, cfg, user_dn: str, password: str) -> None:
            self.verify_calls.append({"dn": user_dn, "password": password})
            if self.fail_verify:
                raise ldap_service.LdapError("auth", "LDAP 账号或密码错误（fake）")
            matched = next((u for u in self.users.values() if u.dn == user_dn), None)
            if matched is None or matched.password != password:
                raise ldap_service.LdapError("auth", "LDAP 账号或密码错误（fake）")

    controller = _Controller()
    monkeypatch.setattr(ldap_service, "_search_user_sync", controller._search)
    monkeypatch.setattr(ldap_service, "_verify_password_sync", controller._verify)
    return controller


@pytest_asyncio.fixture
async def ldap_cfg(db):
    """预置一行启用中的 LDAP 配置（id=1 单例行），host ldap.test、port 389。"""
    from app.models import LdapConfig

    row = LdapConfig(
        id=1,
        enabled=True,
        server_host="ldap.test",
        server_port=389,
        encryption="none",
        bind_dn="cn=svc,dc=test",
        bind_password_enc=encrypt_secret("svc-secret"),
        user_base_dn="ou=people,dc=test",
        user_filter="(uid={username})",
        attr_uid="uid",
        attr_mail="mail",
        attr_display_name="cn",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
