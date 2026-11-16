"""OV 响应解析适配层（90 §5：字段为待抓包假设，校准只改本文件与 payloads.py）。"""
from app.services.openviking.payloads import (
    extract_account,
    extract_accounts_list,
    extract_admin_key,
    extract_remote_role,
    extract_remote_user_id,
    extract_user_key,
    extract_users_list,
)


def test_extract_user_key_candidates():
    assert extract_user_key({"key": "secret-1"}) == "secret-1"
    assert extract_user_key({"api_key": "secret-2"}) == "secret-2"
    assert extract_user_key({"user_key": "secret-3"}) == "secret-3"


def test_extract_user_key_unknown_shape_is_none():
    assert extract_user_key({"nope": "x"}) is None
    assert extract_user_key(None) is None
    assert extract_user_key(["not", "dict"]) is None
    assert extract_user_key({"key": 123}) is None


def test_extract_admin_key_flat_and_nested():
    assert extract_admin_key({"admin_key": "ak-1"}) == "ak-1"
    assert extract_admin_key({"admin": {"api_key": "ak-2"}}) == "ak-2"
    assert extract_admin_key({"admin_user": {"key": "ak-3"}}) == "ak-3"
    assert extract_admin_key({}) is None
    assert extract_admin_key("garbage") is None


def test_extract_users_list_shapes():
    assert [extract_remote_user_id(u) for u in extract_users_list(
        {"users": [{"user_id": "a"}, {"user_id": "b"}]})] == ["a", "b"]
    assert [extract_remote_user_id(u) for u in extract_users_list(
        {"items": [{"id": "c"}]})] == ["c"]
    assert [extract_remote_user_id(u) for u in extract_users_list(
        [{"userId": "d"}])] == ["d"]
    assert extract_users_list({"unexpected": 1}) == []
    assert extract_users_list(None) == []


def test_extract_remote_role_normalized():
    assert extract_remote_role({"role": "admin"}) == "admin"
    assert extract_remote_role({"role": "user"}) == "user"
    assert extract_remote_role({"role": "ROOT"}) is None
    assert extract_remote_role({}) is None


def test_extract_accounts_list_and_account():
    assert extract_accounts_list({"accounts": [{"account_id": "a"}]}) == [{"account_id": "a"}]
    assert extract_accounts_list([{"id": "b"}]) == [{"id": "b"}]
    assert extract_accounts_list({}) == []
    assert extract_account({"account_id": "a", "settings": {}}) == {"account_id": "a", "settings": {}}
    assert extract_account(None) is None


def test_extract_admin_key_accepts_user_key_in_create_result():
    # v0.5.4 真机 create_account 内层：初始 admin key 即 user_key 字段。
    assert extract_admin_key(
        {"account_id": "a", "admin_user_id": "m", "user_key": "k-144"}
    ) == "k-144"


def test_extract_users_list_from_bare_inner_array():
    users = extract_users_list([{"user_id": "u1", "role": "admin"}])
    assert len(users) == 1
    assert extract_remote_user_id(users[0]) == "u1"


def test_extract_users_list_from_summary_dict():
    users = extract_users_list({"users": [{"user_id": "u2"}], "total": 1, "key_count": 1})
    assert [extract_remote_user_id(u) for u in users] == ["u2"]


def test_extract_user_key_from_inner_result():
    assert extract_user_key({"user_id": "u", "user_key": "k"}) == "k"
