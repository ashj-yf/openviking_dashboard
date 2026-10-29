"""异步数据库引擎与会话。"""
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=settings.debug, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _set_sqlite_pragma(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def attach_sqlite_pragma(eng: AsyncEngine) -> None:
    """对 SQLite engine 的每个底层连接打开外键约束（aiosqlite 默认关闭）。"""
    event.listen(eng.sync_engine, "connect", _set_sqlite_pragma)


attach_sqlite_pragma(engine)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
