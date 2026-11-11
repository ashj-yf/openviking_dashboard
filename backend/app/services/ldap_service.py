"""LDAP 认证领域服务：两级 bind、纯 DB 单源配置存取与连接测试。

ldap3 为同步库，目录操作一律经 asyncio.to_thread 包装；_search_user_sync /
_verify_password_sync 两个同步接缝函数是测试假件（conftest.fake_ldap）的替换点。
配置仅存 ldap_config 表（整表恒只有 id=1 一行），不引入任何 env / Settings 字段。
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import DashboardUser, LdapConfig
from app.schemas.ldap import LdapConfigUpdate, LdapTestResult


class LdapError(Exception):
    """LDAP 业务失败。stage："search"（检索/服务绑定阶段）或 "auth"（用户验密阶段）。"""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        self.message = message
        super().__init__(message)


class LdapUnavailableError(LdapError):
    """LDAP 服务不可用（网络/超时类），stage 恒为 "connect"。"""

    def __init__(self, message: str = "LDAP 服务不可用，请联系管理员") -> None:
        super().__init__("connect", message)


async def load_ldap_config(db: AsyncSession) -> LdapConfig | None:
    """读取配置单例行（约定 id=1），不存在返回 None。"""
    return (await db.scalars(select(LdapConfig).where(LdapConfig.id == 1))).first()


async def ldap_mode_enabled(db: AsyncSession) -> bool:
    """LDAP 认证模式是否生效：配置存在且 enabled 为真。"""
    cfg = await load_ldap_config(db)
    return bool(cfg is not None and cfg.enabled)


async def upsert_ldap_config(
    db: AsyncSession, payload: LdapConfigUpdate, actor: DashboardUser | None
) -> LdapConfig:
    """保存配置单例行（id=1，不存在则创建）。

    bind_password 为 None 表示未提供：保留旧密文；否则 Fernet 加密覆盖。
    记 updated_at/updated_by_id（审计日志由路由层另行记录）。
    """
    row = await load_ldap_config(db)
    if row is None:
        row = LdapConfig(id=1, bind_password_enc="")
        db.add(row)
    row.enabled = payload.enabled
    row.server_host = payload.server_host
    row.server_port = payload.server_port
    row.encryption = payload.encryption
    # 模型列非空：未提供 bind_dn 时落空串
    row.bind_dn = payload.bind_dn or ""
    if payload.bind_password is not None:
        row.bind_password_enc = encrypt_secret(payload.bind_password)
    row.user_base_dn = payload.user_base_dn
    row.user_filter = payload.user_filter
    row.attr_uid = payload.attr_uid
    row.attr_mail = payload.attr_mail
    row.attr_display_name = payload.attr_display_name
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by_id = actor.id if actor is not None else None
    await db.commit()
    await db.refresh(row)
    return row


def _build_server(cfg: LdapConfig):
    """按加密方式构造 Server：5 秒连接超时；ldaps 走 use_ssl，starttls 后置升级。"""
    from ldap3 import Server, Tls

    return Server(
        cfg.server_host,
        port=cfg.server_port,
        use_ssl=cfg.encryption == "ldaps",
        tls=Tls() if cfg.encryption == "starttls" else None,
        connect_timeout=5,
        get_info=None,
    )


def _open_and_bind(cfg: LdapConfig, dn: str | None, password: str | None):
    """建连（含 STARTTLS 升级）并以给定 DN bind；失败时自行关连再抛出。

    网络类失败抛 LDAPCommunicationError 系，凭据类失败抛其余 LDAPException 系，
    异常分类由调用方接缝函数处理。
    """
    from ldap3 import Connection
    from ldap3.core.exceptions import LDAPException

    conn = Connection(
        _build_server(cfg),
        user=dn or None,
        password=password,
        auto_bind=False,
        raise_exceptions=True,
        receive_timeout=5,
        check_names=False,
    )
    try:
        conn.open()
        if cfg.encryption == "starttls":
            conn.start_tls()
        conn.bind()
    except BaseException:
        _close_quietly(conn)
        raise
    return conn


def _close_quietly(conn) -> None:
    """尽力关闭连接；ldap3 open 失败时不会关掉已创建的 socket，这里兜底防泄漏。"""
    from ldap3.core.exceptions import LDAPException

    try:
        conn.unbind()
    except LDAPException:
        pass
    finally:
        sock = getattr(conn, "socket", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _first_attr(attributes: dict, name: str) -> str:
    """取目录属性首值；缺失/空值回退空串，bytes 解码为文本。"""
    value = attributes.get(name)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _search_user_sync(cfg: LdapConfig, username: str) -> tuple[str, dict[str, str]]:
    """同步接缝：服务 bind（bind_dn 为空则匿名）→ 按过滤器检索用户取首条。

    返回 (user_dn, attrs)，attrs 恒含 uid/mail/display_name 三个映射键（与配置的
    LDAP 属性名解耦）。网络/超时抛 LdapUnavailableError（stage="connect"），
    其余失败抛 LdapError（stage="search"）。
    """
    from ldap3 import SUBTREE
    from ldap3.core.exceptions import (
        LDAPBindError,
        LDAPCommunicationError,
        LDAPException,
    )

    try:
        service_password = (
            decrypt_secret(cfg.bind_password_enc) if cfg.bind_dn else None
        )
    except ValueError as exc:
        raise LdapError("search", "Bind 密码解密失败，请重新保存 LDAP 配置") from exc

    conn = None
    try:
        conn = _open_and_bind(cfg, cfg.bind_dn, service_password)
        conn.search(
            search_base=cfg.user_base_dn,
            search_filter=cfg.user_filter.format(username=username),
            search_scope=SUBTREE,
            attributes=[cfg.attr_uid, cfg.attr_mail, cfg.attr_display_name],
        )
        entries = [r for r in conn.response if r.get("type") == "searchResEntry"]
        if not entries:
            raise LdapError("search", "未在 LDAP 中找到该用户，请检查用户过滤器")
        entry = entries[0]
        attrs = {
            "uid": _first_attr(entry.get("attributes", {}), cfg.attr_uid),
            "mail": _first_attr(entry.get("attributes", {}), cfg.attr_mail),
            "display_name": _first_attr(entry.get("attributes", {}), cfg.attr_display_name),
        }
        return str(entry["dn"]), attrs
    except LDAPCommunicationError as exc:
        raise LdapUnavailableError() from exc
    except LDAPBindError as exc:
        raise LdapError(
            "search",
            "服务账号绑定失败，请检查 Bind DN 与 Bind 密码"
            if cfg.bind_dn
            else "匿名绑定被 LDAP 服务器拒绝",
        ) from exc
    except LDAPException as exc:
        raise LdapError(
            "search", f"LDAP 用户搜索失败，请检查 Base DN 与用户过滤器：{exc}"
        ) from exc
    finally:
        if conn is not None:
            _close_quietly(conn)


def _verify_password_sync(cfg: LdapConfig, user_dn: str, password: str) -> None:
    """同步接缝：以用户 DN 二次 bind 验证密码（两级 bind 的第二级）。

    验密通过静默返回；凭据错误抛 LdapError（stage="auth"），网络/超时抛
    LdapUnavailableError（stage="connect"）。
    """
    from ldap3.core.exceptions import LDAPCommunicationError, LDAPException

    try:
        conn = _open_and_bind(cfg, user_dn, password)
    except LDAPCommunicationError as exc:
        raise LdapUnavailableError() from exc
    except LDAPException as exc:
        raise LdapError("auth", "LDAP 账号或密码错误") from exc
    _close_quietly(conn)


async def ldap_authenticate(
    db: AsyncSession, username: str, password: str
) -> tuple[str, dict[str, str]]:
    """LDAP 登录校验：第一级 bind 检索用户 DN，第二级 bind 验证密码。

    成功返回 (user_dn, attrs)；失败抛 LdapError / LdapUnavailableError。
    """
    cfg = await load_ldap_config(db)
    if cfg is None or not cfg.enabled:
        raise LdapError("search", "LDAP 认证未启用")
    user_dn, attrs = await asyncio.to_thread(_search_user_sync, cfg, username)
    await asyncio.to_thread(_verify_password_sync, cfg, user_dn, password)
    return user_dn, attrs


async def test_ldap_config(
    payload: LdapConfigUpdate, *, probe_username: str = "smoke-probe"
) -> LdapTestResult:
    """配置连接测试：依次探测 connect→服务 bind→用户搜索，返回首个失败阶段。

    Bind 密码未提供（None/空串）时不发起探测，直接提示补全；成功返回 stage="ok"。
    """
    if not payload.bind_password:
        return LdapTestResult(
            ok=False, stage="config", message="请填写 Bind 密码后再测试"
        )
    cfg = LdapConfig(
        id=1,
        enabled=True,
        server_host=payload.server_host,
        server_port=payload.server_port,
        encryption=payload.encryption,
        bind_dn=payload.bind_dn or "",
        bind_password_enc=encrypt_secret(payload.bind_password),
        user_base_dn=payload.user_base_dn,
        user_filter=payload.user_filter,
        attr_uid=payload.attr_uid,
        attr_mail=payload.attr_mail,
        attr_display_name=payload.attr_display_name,
    )
    try:
        await asyncio.to_thread(_search_user_sync, cfg, probe_username)
    except LdapError as exc:
        return LdapTestResult(ok=False, stage=exc.stage, message=exc.message)
    return LdapTestResult(ok=True, stage="ok", message="连接、绑定与用户搜索均正常")
