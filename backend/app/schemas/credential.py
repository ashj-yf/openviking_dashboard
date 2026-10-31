"""我的凭证请求/响应；Revealed 是唯一允许携带明文 key 的响应模型。"""
from datetime import datetime

from pydantic import BaseModel


class CredentialView(BaseModel):
    endpoint: str
    account_id: str
    ov_user_id: str
    has_key: bool
    key_masked: str | None = None
    key_hint: str | None = None
    seed_used: bool = False
    key_synced_at: datetime | None = None


class RevealedKeyOut(CredentialView):
    key: str
