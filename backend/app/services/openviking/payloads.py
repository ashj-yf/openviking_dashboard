"""OpenViking 响应结构解析（唯一适配点）。

90-openviking-api §5 标注三个响应体上线前必须抓真实响应校准：
POST /admin/accounts、POST .../users、POST .../users/{id}/key。
下列候选键覆盖常见命名；抓包后如字段不同，只改本模块与 test_ov_payloads.py，
业务代码一律经本模块取数，不直接索引 OV 响应字段。
"""
from typing import Any


def _first_key(payload: Any, *keys: str) -> Any:
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if v is not None:
                return v
    return None


def _as_str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def extract_user_key(payload: Any) -> str | None:
    """注册/签发/重签响应中的 user key；候选: key / api_key / user_key / apiKey。"""
    return _as_str(_first_key(payload, "key", "api_key", "user_key", "apiKey"))


def extract_admin_key(payload: Any) -> str | None:
    """创建账户响应中的初始管理员 key；v0.5.4 内层即 user_key，另支持历史平铺与 admin/admin_user 嵌套。"""
    flat = _as_str(_first_key(payload, "user_key", "admin_key", "admin_api_key"))
    if flat:
        return flat
    nested = _first_key(payload, "admin", "admin_user", "initial_admin")
    if isinstance(nested, dict):
        return extract_user_key(nested)
    return None


def extract_users_list(payload: Any) -> list[dict]:
    """账户下用户列表；容忍 {users|items|data: [...]} 与裸数组三种形态。"""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    for k in ("users", "items", "data"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def extract_remote_user_id(u: dict) -> str | None:
    return _as_str(_first_key(u, "user_id", "id", "userId"))


def extract_remote_role(u: dict) -> str | None:
    """OV 侧角色仅认 admin/user，其余值（含 ROOT 等）一律返回 None。"""
    v = _first_key(u, "role", "ov_role")
    return v if v in ("admin", "user") else None


def extract_accounts_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    for k in ("accounts", "items", "data"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def extract_account(payload: Any) -> dict | None:
    return payload if isinstance(payload, dict) else None
