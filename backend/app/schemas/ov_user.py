from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OvUserCreate(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field("user", description="admin / user")
    seed: str | None = None


class OvUserUpdate(BaseModel):
    role: str | None = Field(None, description="admin / user")


class OvUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    ov_user_id: str
    role: str
    synced_at: datetime | None = None


class KeyIssueRequest(BaseModel):
    seed: str | None = Field(None, description="留空随机签发；相同 seed 可确定性重建")


class KeyIssueResult(BaseModel):
    """密钥签发结果。api_key 明文仅本次返回，后端不落库。"""

    account_id: str
    user_id: str
    api_key: str
    is_new: bool = True
    key_hint: str | None = None
