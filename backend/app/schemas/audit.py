from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_name: str
    action: str
    target_type: str | None
    target_id: str | None
    detail_json: str | None
    ip: str | None
    created_at: datetime | None
