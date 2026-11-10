"""认证相关请求/响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class MeOut(BaseModel):
    """当前登录用户信息；只暴露 OV key 是否存在的布尔位，不含任何密文。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    is_active: bool
    tenant_id: int | None = None
    account_id: str | None = None
    ov_user_id: str | None = None
    ov_role: str | None = None
    has_ov_key: bool = False
    key_synced_at: datetime | None = None
    must_change_password: bool = False
    last_login_at: datetime | None = None
    # 该账号是否为 .env 配置的超管（UI 不可修改，前端据此渲染保护态）
    is_env_admin: bool = False


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)
