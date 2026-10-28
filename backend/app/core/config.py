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

    # Fernet 密钥加密主密钥（留存 user key 用），与 JWT_SECRET 独立设置
    secret_key: str = Field(default="change-me")

    first_admin_username: str = ""
    first_admin_password: str = ""

    openviking_base_url: str = "https://ov.19951112.xyz"
    openviking_root_key: str = ""
    http_timeout_seconds: float = 20.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


class ConfigError(RuntimeError):
    """启动配置校验失败。"""


_EXAMPLE_SECRETS = {"change-me", "change-me-to-a-long-random-string"}


def validate_settings(s: Settings) -> None:
    """发现问题时抛 ConfigError，消息逐条列出；DEBUG 下放宽 root key 与示例密钥检查。"""
    problems: list[str] = []

    if not s.first_admin_username.strip() or not s.first_admin_password.strip():
        problems.append("- FIRST_ADMIN_USERNAME / FIRST_ADMIN_PASSWORD 不能为空")
    if not s.jwt_secret:
        problems.append("- JWT_SECRET 不能为空")
    if not s.secret_key:
        problems.append("- SECRET_KEY 不能为空")

    if not s.debug:
        if s.jwt_secret in _EXAMPLE_SECRETS:
            problems.append("- JWT_SECRET 不能使用示例值，请改为足够长的随机字符串")
        if s.secret_key in _EXAMPLE_SECRETS:
            problems.append("- SECRET_KEY 不能使用示例值，请改为足够长的随机字符串")
        if not s.openviking_root_key:
            problems.append("- OPENVIKING_ROOT_KEY 在生产环境（DEBUG=false）下不能为空")

    if problems:
        raise ConfigError("启动配置校验失败：\n" + "\n".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
