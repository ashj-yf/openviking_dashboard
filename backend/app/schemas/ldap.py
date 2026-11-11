"""LDAP 认证配置请求/响应与连接测试结果模型（B3 路由直接复用）。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LdapConfigUpdate(BaseModel):
    """配置保存请求体；bind_password 为 None 表示保持已存密文不变。"""

    enabled: bool = False
    server_host: str = Field(min_length=1, max_length=256)
    server_port: int = Field(ge=1, le=65535)
    encryption: Literal["none", "starttls", "ldaps"] = "none"
    bind_dn: str | None = Field(default=None, max_length=256)
    bind_password: str | None = None
    user_base_dn: str = Field(min_length=1, max_length=256)
    user_filter: str = Field(min_length=1, max_length=256)
    attr_uid: str = Field(min_length=1, max_length=64)
    attr_mail: str = Field(min_length=1, max_length=64)
    attr_display_name: str = Field(min_length=1, max_length=64)


class LdapConfigOut(BaseModel):
    """配置读取响应：永不回显 bind 密码，仅以 has_bind_password 标记是否已保存。"""

    enabled: bool
    server_host: str
    server_port: int
    encryption: str
    bind_dn: str | None = None
    user_base_dn: str
    user_filter: str
    attr_uid: str
    attr_mail: str
    attr_display_name: str
    has_bind_password: bool
    updated_at: datetime | None = None


class LdapTestResult(BaseModel):
    """连接测试结果；stage ∈ config / connect / search / ok，message 为中文分类文案。"""

    ok: bool
    stage: str
    message: str
