"""启动期 schema 增量迁移。

本项目不引入 Alembic：全新建表交给 lifespan 的 create_all，而 create_all
不会改动已存在的表，因此这里只负责给旧库补上后续版本新增的列和索引。
每个动作都先探测、后执行，幂等可重复；返回已应用的动作名供启动日志记录。
"""
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Connection

from app.models import DashboardUser

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

    缺失列逐条 ALTER TABLE 补齐；password_hash 仍为 NOT NULL 的存量表按模型
    整表重建以解除非空约束（SQLite 无 ALTER MODIFY）；LDAP 用户名唯一索引用
    IF NOT EXISTS 保证幂等。ldap_config 等新表交给 create_all，此处不处理。
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

    if _password_hash_is_not_null(sync_conn):
        _rebuild_dashboard_users_table(sync_conn)
        applied.append("dashboard_users: rebuild table (password_hash → nullable)")

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


def _password_hash_is_not_null(sync_conn: Connection) -> bool:
    """存量表 password_hash 是否仍带 NOT NULL（模型已改 nullable，重建以解除）。"""
    for col in inspect(sync_conn).get_columns("dashboard_users"):
        if col["name"] == "password_hash":
            return not bool(col.get("nullable", True))
    return False


def _rebuild_dashboard_users_table(sync_conn: Connection) -> None:
    """按当前模型重建 dashboard_users：新表 DDL 由模型编译生成，保证零漂移。

    遵循 sqlite.org/lang_altertable 官方重建规程：先在迁移连接上关闭外键
    （PRAGMA foreign_keys 仅在无挂起事务时生效，关闭后立即回读校验，失效
    即抛异常——外键动作生效时 DROP 父表会把 audit_logs.actor_user_id 静默
    置空，审计归因不可丢）；重建后 PRAGMA foreign_key_check 校验无违规，
    最后显式恢复 ON（连接池化复用，connect 事件不会重放，不能依赖隐式恢复）。

    重建本体：建 dashboard_users_new → 按"共有列名"对齐搬运数据（模型有而
    旧表还没有的列，由新表列默认值兜底）→ DROP 旧表 → RENAME 回原名 → 按
    模型逐个重建索引（DROP 会连带丢掉 username/tenant_id 普通索引与
    ldap_username 唯一索引，必须补回；随后的唯一索引 IF NOT EXISTS 步骤
    照常幂等）。
    """
    from sqlalchemy import Column, Integer, Table
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import sqlite

    table = DashboardUser.__table__
    existing = {col["name"] for col in inspect(sync_conn).get_columns("dashboard_users")}
    shared = [col.name for col in table.columns if col.name in existing]

    sync_conn.execute(text("PRAGMA foreign_keys=OFF"))
    if sync_conn.execute(text("PRAGMA foreign_keys")).scalar():
        # OFF 未生效（连接存在挂起事务时该 PRAGMA 是 no-op）：拒绝重建，
        # 防止外键动作生效时 DROP 父表静默置空 audit_logs 归因
        raise RuntimeError(
            "无法关闭外键约束（连接存在挂起事务），拒绝重建 dashboard_users："
            "外键动作生效时 DROP 父表会置空 audit_logs 归因"
        )
    try:
        # 新表拷进临时 metadata；放一个最小 tenants 影子表，供 tenant_id 外键在
        # DDL 编译时解析引用目标（不会创建影子表，仅影响编译出的 REFERENCES 文本）
        tmp_metadata = MetaData()
        Table("tenants", tmp_metadata, Column("id", Integer, primary_key=True))
        new_table = table.to_metadata(tmp_metadata, name=f"{table.name}_new")
        # DDL 隐式提交：若上次重建中途被打断，可能残留 _new 表，先行清除保证可重入
        sync_conn.execute(text("DROP TABLE IF EXISTS dashboard_users_new"))
        sync_conn.execute(text(str(CreateTable(new_table).compile(dialect=sqlite.dialect()))))
        column_list = ", ".join(shared)
        sync_conn.execute(
            text(
                f"INSERT INTO dashboard_users_new ({column_list}) "
                f"SELECT {column_list} FROM dashboard_users"
            )
        )
        sync_conn.execute(text("DROP TABLE dashboard_users"))
        sync_conn.execute(text("ALTER TABLE dashboard_users_new RENAME TO dashboard_users"))
        # DROP 旧表连带丢掉其全部索引：按模型逐个补回（含 ldap_username 唯一索引）
        for index in sorted(table.indexes, key=lambda ix: ix.name or ""):
            index.create(sync_conn)
        # 官方规程顺序：先提交重建事务（否则 PRAGMA foreign_keys=ON 因存在
        # 挂起事务而静默失效），再做外键校验，最后恢复外键。在 engine.begin()
        # 上下文里不能关 SQLAlchemy 事务对象，故走 DBAPI 层提交（pysqlite
        # legacy 语义下 DDL 本就逐步自动提交，提前提交不改变可观测语义）
        sync_conn.connection.commit()
        violations = sync_conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        if violations:
            names = "、".join(sorted({str(row[0]) for row in violations}))
            raise RuntimeError(
                f"dashboard_users 重建后外键校验失败，违规涉及表: {names}；"
                "请先修复存量数据再启动"
            )
    finally:
        sync_conn.execute(text("PRAGMA foreign_keys=ON"))
