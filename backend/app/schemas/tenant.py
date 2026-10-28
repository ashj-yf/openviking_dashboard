from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=128, description="OpenViking account_id")
    admin_user_id: str = Field(..., min_length=1, max_length=128, description="账户初始管理员 user_id")
    seed: str | None = Field(None, description="确定性密钥种子，留空则服务端随机")
    display_name: str | None = None
    remark: str | None = None
    # 若 OpenViking 返回管理员 key 失败则不保存
    save_admin_key: bool = True


class TenantUpdate(BaseModel):
    display_name: str | None = None
    remark: str | None = None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ov_account_id: str
    admin_user_id: str
    display_name: str | None
    remark: str | None
    has_admin_key: bool = False
    user_count: int = 0
    created_at: datetime | None = None
    synced_at: datetime | None = None
