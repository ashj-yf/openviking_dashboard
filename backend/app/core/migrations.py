"""启动期 schema 增量迁移。

本项目不引入 Alembic：全新建表交给 lifespan 的 create_all，而 create_all
不会改动已存在的表，因此这里只负责给旧库补上后续版本新增的列和索引。
每个动作都先探测、后执行，幂等可重复；返回已应用的动作名供启动日志记录。
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

# dashboard_users 首版之后新增的列：列名 -> ALTER TABLE 用的列定义片段
# （须与 DashboardUser 模型上的列定义保持一致）
_DASHBOARD_USERS_NEW_COLUMNS: dict[str, str] = {
    "auth_source": "VARCHAR(8) NOT NULL DEFAULT 'local'",
    "ldap_username": "VARCHAR(128)",
    "ldap_dn": "VARCHAR(256)",
    "bound_at": "DATETIME",
}

# LDAP 绑定用户名唯一索引（与模型的 Index 同名）
_LDAP_USERNAME_INDEX = "uq_dashboard_users_ldap_username"


def apply_schema_upgrades(sync_conn: Connection) -> list[str]:
    """对既有库做增量 schema 升级，返回已应用的动作名列表。

    缺失列逐条 ALTER TABLE 补齐；LDAP 用户名唯一索引用 IF NOT EXISTS 保证
    幂等。ldap_config 等新表交给 create_all，此处不处理。
    """
    applied: list[str] = []
    inspector = inspect(sync_conn)
    existing_columns = {col["name"] for col in inspector.get_columns("dashboard_users")}
    for name, definition in _DASHBOARD_USERS_NEW_COLUMNS.items():
        if name in existing_columns:
            continue
        sync_conn.execute(
            text(f"ALTER TABLE dashboard_users ADD COLUMN {name} {definition}")
        )
        applied.append(f"dashboard_users: ADD COLUMN {name}")

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("dashboard_users")}
    if _LDAP_USERNAME_INDEX not in existing_indexes:
        sync_conn.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_LDAP_USERNAME_INDEX} "
                "ON dashboard_users (ldap_username)"
            )
        )
        applied.append(f"dashboard_users: CREATE UNIQUE INDEX {_LDAP_USERNAME_INDEX}")
    return applied
