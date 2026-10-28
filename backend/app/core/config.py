"""应用配置：从环境变量 / .env 读取。"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "OpenViking Dashboard"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/dashboard.db"

    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    first_admin_username: str = "admin"
    first_admin_password: str = "admin123"

    openviking_base_url: str = "http://127.0.0.1:1933"
    openviking_root_key: str = ""
    http_timeout_seconds: float = 20.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
