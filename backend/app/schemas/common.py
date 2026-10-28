"""通用响应模型。"""
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class IdOut(BaseModel):
    id: int


# OpenViking 返回的时间字段不统一，统一以宽松类型接收
LooseDatetime = datetime | str | None


class OVIdentifiers(BaseModel):
    account_id: str = Field(serialization_alias="accountId")
    user_id: str = Field(serialization_alias="userId")
