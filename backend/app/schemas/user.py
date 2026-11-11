"""用户管理相关请求/响应模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tenant import ID_PATTERN


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    tenant_id: int | None = None
    ov_user_id: str | None = Field(default=None, pattern=ID_PATTERN)
    role: Literal["team_admin", "user"] = "user"
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    # 认证来源：local（本机密码）/ ldap（目录统一认证）
    auth_source: Literal["local", "ldap"] = "local"
    is_active: bool
    tenant_id: int | None = None
    account_id: str | None = None
    ov_user_id: str | None = None
    ov_role: str | None = None
    has_key: bool = False
    key_state: Literal["current", "pending"] = "pending"
    key_synced_at: datetime | None = None
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    # 该账号是否为 .env 配置的超管（UI 不可修改，前端据此禁用操作入口）
    is_env_admin: bool = False


class UserRoleRequest(BaseModel):
    role: Literal["team_admin", "user"]


class UserProvisionRequest(BaseModel):
    """LDAP JIT 用户开通：为自动建档的用户补全团队归属与 OV 身份。"""

    tenant_id: int
    role: Literal["team_admin", "user"] = "user"
    ov_user_id: str | None = Field(default=None, pattern=ID_PATTERN)
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
    regenerate_key: bool = False
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class KeyRegenerateRequest(BaseModel):
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class UserSyncReport(BaseModel):
    account_id: str
    ov_user_id: str
    ov_exists: bool
    local_ov_role: str | None = None
    ov_role: str | None = None
    consistent: bool
