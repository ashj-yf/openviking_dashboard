"""团队相关请求/响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class TenantListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: str
    display_name: str | None = None
    remark: str | None = None
    admin_user_id: str
    user_count: int
    synced_at: datetime | None = None
    created_at: datetime | None = None


class TenantDetailOut(TenantListItem):
    ov_account: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
    ov_error: str | None = None


class TenantUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    remark: str | None = Field(default=None, min_length=1, max_length=500)


class SyncUserInfo(BaseModel):
    ov_user_id: str
    ov_role: str | None = None
    username: str | None = None


class TenantSyncReport(BaseModel):
    account_id: str
    ov_user_count: int
    local_user_count: int
    matched: int
    missing_local: list[SyncUserInfo] = []
    extra_local: list[SyncUserInfo] = []
    synced_at: datetime


class TenantCreateRequest(BaseModel):
    account_id: str = Field(pattern=ID_PATTERN)
    admin_user_id: str = Field(pattern=ID_PATTERN)
    admin_username: str = Field(min_length=1, max_length=64)
    admin_password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    remark: str | None = Field(default=None, min_length=1, max_length=500)
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class TenantCreatedOut(BaseModel):
    id: int
    account_id: str
    admin_user_id: str
    team_admin_id: int
    team_admin_username: str
    key_provisioned: bool


class TenantDeleteRequest(BaseModel):
    confirm: bool = False
