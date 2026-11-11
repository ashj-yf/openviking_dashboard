"""ldap_service 单元测试：两级 bind、配置存取与连接测试（经 fake_ldap 接缝假件）。"""
import pytest

from app.core.crypto import decrypt_secret
from app.schemas.ldap import LdapConfigUpdate, LdapTestResult
from app.services import ldap_service
from conftest import FakeUser


def _payload(**kw) -> LdapConfigUpdate:
    """构造合法配置请求体；bind_password 默认提供，各测试按需覆盖。"""
    base = dict(
        server_host="ldap.test",
        server_port=389,
        encryption="none",
        bind_dn="cn=svc,dc=test",
        bind_password="svc-secret",
        user_base_dn="ou=people,dc=test",
        user_filter="(uid={username})",
        attr_uid="uid",
        attr_mail="mail",
        attr_display_name="cn",
    )
    base.update(kw)
    return LdapConfigUpdate(**base)


async def test_filter_format_and_attr_mapping(db, ldap_cfg, fake_ldap):
    fake_ldap.users["alice"] = FakeUser("cn=alice,ou=people,dc=test", "pw", "alice@t", "Alice")
    user_dn, attrs = await ldap_service.ldap_authenticate(db, "alice", "pw")
    assert user_dn == "cn=alice,ou=people,dc=test"
    # 映射键与配置的 LDAP 属性名解耦：恒为 uid / mail / display_name
    assert attrs == {"uid": "alice", "mail": "alice@t", "display_name": "Alice"}
    assert fake_ldap.search_calls == [{"username": "alice"}]


async def test_ldap_authenticate_success(db, ldap_cfg, fake_ldap):
    fake_ldap.users["bob"] = FakeUser("cn=bob,ou=people,dc=test", "bobpw", "b@t", "Bob")
    user_dn, _ = await ldap_service.ldap_authenticate(db, "bob", "bobpw")
    # 两级 bind：第二级验密收到的是第一级检索到的 DN 与登录口令
    assert user_dn == "cn=bob,ou=people,dc=test"
    assert fake_ldap.verify_calls == [
        {"dn": "cn=bob,ou=people,dc=test", "password": "bobpw"}
    ]


async def test_ldap_authenticate_wrong_password_raises_stage_auth(db, ldap_cfg, fake_ldap):
    fake_ldap.users["carol"] = FakeUser("cn=carol,ou=people,dc=test", "right", "c@t", "Carol")
    with pytest.raises(ldap_service.LdapError) as ei:
        await ldap_service.ldap_authenticate(db, "carol", "wrong")
    assert ei.value.stage == "auth"
    assert not isinstance(ei.value, ldap_service.LdapUnavailableError)
    # 检索成功后才进入验密：两个阶段各执行一次
    assert len(fake_ldap.search_calls) == 1
    assert len(fake_ldap.verify_calls) == 1


async def test_ldap_authenticate_connect_fail_raises_unavailable(db, ldap_cfg, fake_ldap):
    fake_ldap.fail_connect = True
    with pytest.raises(ldap_service.LdapUnavailableError) as ei:
        await ldap_service.ldap_authenticate(db, "dave", "pw")
    assert ei.value.stage == "connect"
    # 连接失败不得进入验密阶段（Review Focus 1：两级 bind 的接缝层证明）
    assert fake_ldap.verify_calls == []


async def test_response_timeout_classified_unavailable(db, ldap_cfg, monkeypatch):
    """响应超时归入不可用类：LDAPResponseTimeoutError 不继承 LDAPCommunicationError，
    两级 bind 任一级超时都必须抛 LdapUnavailableError，不得误报凭据错误。"""
    from ldap3.core.exceptions import LDAPResponseTimeoutError

    def _timeout(cfg, dn, password):
        raise LDAPResponseTimeoutError("timed out")

    monkeypatch.setattr(ldap_service, "_open_and_bind", _timeout)
    # 第一级 bind（服务 bind + 检索）超时
    with pytest.raises(ldap_service.LdapUnavailableError) as ei:
        await ldap_service.ldap_authenticate(db, "ernie", "pw")
    assert ei.value.stage == "connect"

    # 第二级 bind（验密）超时：检索放行后验密超时同样不可用
    monkeypatch.setattr(
        ldap_service,
        "_search_user_sync",
        lambda cfg, username: (
            "cn=ernie,ou=people,dc=test",
            {"uid": "ernie", "mail": "", "display_name": ""},
        ),
    )
    with pytest.raises(ldap_service.LdapUnavailableError) as ei:
        await ldap_service.ldap_authenticate(db, "ernie", "pw")
    assert ei.value.stage == "connect"


async def test_ldap_mode_enabled_false_without_row(db):
    assert await ldap_service.load_ldap_config(db) is None
    assert await ldap_service.ldap_mode_enabled(db) is False


async def test_upsert_keep_password_when_omitted(db, ldap_cfg, make_user):
    actor = await make_user("cfgadmin", "Passw0rd!", "admin")
    row = await ldap_service.upsert_ldap_config(db, _payload(bind_password=None), actor)
    assert row.id == 1
    # bind_password 未提供（None）：保留 ldap_cfg 预置的旧密文
    assert decrypt_secret(row.bind_password_enc) == "svc-secret"
    assert row.updated_by_id == actor.id
    assert row.updated_at is not None


async def test_upsert_replaces_password(db):
    row = await ldap_service.upsert_ldap_config(db, _payload(bind_password="first-secret"), None)
    # 首次保存创建 id=1 单例行
    assert row.id == 1
    assert (row.enabled, row.server_host, row.server_port, row.encryption) == (
        False,
        "ldap.test",
        389,
        "none",
    )
    assert decrypt_secret(row.bind_password_enc) == "first-secret"
    row = await ldap_service.upsert_ldap_config(db, _payload(bind_password="second-secret"), None)
    assert row.id == 1
    assert decrypt_secret(row.bind_password_enc) == "second-secret"
    # 再次留空不覆盖
    row = await ldap_service.upsert_ldap_config(db, _payload(bind_password=None), None)
    assert decrypt_secret(row.bind_password_enc) == "second-secret"
    assert row.updated_by_id is None


async def test_test_config_empty_password_stage_config(fake_ldap):
    result = await ldap_service.test_ldap_config(_payload(bind_password=None))
    assert isinstance(result, LdapTestResult)
    assert (result.ok, result.stage, result.message) == (
        False,
        "config",
        "请填写 Bind 密码后再测试",
    )
    # 未发起任何探测
    assert fake_ldap.search_calls == []


async def test_bad_user_filter_placeholder_raises_search_stage(db):
    """管理员过滤器占位符笔误（{user} ≠ {username}）必须归一为 LdapError(search)，
    不得让裸 KeyError 冒泡导致所有 LDAP 登录一律 500。"""
    from app.models import LdapConfig

    cfg = LdapConfig(
        id=1,
        enabled=True,
        server_host="ldap.test",
        server_port=389,
        encryption="none",
        bind_dn="",
        bind_password_enc="",
        user_base_dn="ou=people,dc=test",
        user_filter="(uid={user})",
        attr_uid="uid",
        attr_mail="mail",
        attr_display_name="displayName",
    )
    db.add(cfg)
    await db.commit()
    with pytest.raises(ldap_service.LdapError) as ei:
        await ldap_service.ldap_authenticate(db, "alice", "pw")
    assert ei.value.stage == "search"
    assert "占位符" in ei.value.message
    assert not isinstance(ei.value, ldap_service.LdapUnavailableError)


async def test_config_test_reports_bad_filter_search_stage():
    """连接测试路径同样落到 search 阶段分类提示，而非未分类异常。"""
    result = await ldap_service.test_ldap_config(_payload(user_filter="(uid={user})"))
    assert (result.ok, result.stage) == (False, "search")
    assert "占位符" in result.message


async def test_test_config_ok_and_fail_stages(fake_ldap):
    payload = _payload()
    fake_ldap.users["smoke-probe"] = FakeUser("cn=smoke-probe,ou=people,dc=test", "x", "s@t", "Smoke")
    fake_ldap.fail_connect = True
    result = await ldap_service.test_ldap_config(payload)
    assert (result.ok, result.stage) == (False, "connect")

    fake_ldap.fail_connect = False
    fake_ldap.fail_search = True
    result = await ldap_service.test_ldap_config(payload)
    assert (result.ok, result.stage) == (False, "search")

    fake_ldap.fail_search = False
    result = await ldap_service.test_ldap_config(payload)
    assert result.ok is True
    assert result.stage == "ok"
    # 默认探测账号 smoke-probe，三次调用均记录在案
    assert fake_ldap.search_calls == [{"username": "smoke-probe"}] * 3
