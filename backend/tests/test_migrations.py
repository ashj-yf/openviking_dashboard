"""启动迁移测试：旧库补列 + 唯一索引，新库幂等跳过。"""
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.migrations import apply_schema_upgrades

# 按当前模型更新前的旧 schema 建表（不含本任务新增的 4 列）
_LEGACY_CREATE_SQL = """
CREATE TABLE dashboard_users (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    role VARCHAR(16) NOT NULL,
    is_active BOOLEAN NOT NULL,
    tenant_id INTEGER,
    ov_user_id VARCHAR(128),
    ov_role VARCHAR(32),
    ov_user_key_encrypted TEXT,
    key_synced_at DATETIME,
    must_change_password BOOLEAN NOT NULL,
    last_login_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_LEGACY_INSERT_SQL = (
    "INSERT INTO dashboard_users (username, password_hash, role, is_active, "
    "must_change_password) VALUES (:username, :password_hash, :role, 1, 0)"
)

# 迁移重建会显式恢复连接级外键（PRAGMA foreign_keys=ON）；重建出的
# dashboard_users 带 tenants 外键，测试库需有父表，迁移后的 INSERT 才可行
_TENANTS_CREATE_SQL = "CREATE TABLE tenants (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT)"


def _index_names(conn) -> set[str]:
    return {ix["name"] for ix in inspect(conn).get_indexes("dashboard_users")}


def _column_names(conn) -> set[str]:
    return {col["name"] for col in inspect(conn).get_columns("dashboard_users")}


def test_migration_on_legacy_db_adds_columns_and_unique_index(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as conn:
        conn.execute(text(_TENANTS_CREATE_SQL))
        conn.execute(text(_LEGACY_CREATE_SQL))
        conn.execute(
            text(_LEGACY_INSERT_SQL),
            {"username": "legacy_user", "password_hash": "x" * 60, "role": "user"},
        )
    legacy_engine.dispose()

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        applied = apply_schema_upgrades(conn)

        assert {"auth_source", "ldap_username", "ldap_dn", "bound_at"} <= _column_names(conn)
        assert "uq_dashboard_users_ldap_username" in _index_names(conn)
        legacy_auth_source = conn.execute(
            text("SELECT auth_source FROM dashboard_users WHERE username = 'legacy_user'")
        ).scalar_one()
        assert legacy_auth_source == "local"
        assert any("ADD COLUMN" in action for action in applied)

        # 同一 ldap_username 二次插入必须被唯一索引拦下
        insert_dupe = text(
            "INSERT INTO dashboard_users (username, password_hash, role, is_active, "
            "must_change_password, ldap_username) "
            "VALUES (:username, :password_hash, 'user', 1, 0, :ldap_username)"
        )
        dupe_params = {"password_hash": "x" * 60, "ldap_username": "same"}
        conn.execute(insert_dupe, {**dupe_params, "username": "u2"})
        try:
            conn.execute(insert_dupe, {**dupe_params, "username": "u3"})
        except IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("重复 ldap_username 未触发唯一索引冲突")
    engine.dispose()


async def test_migration_on_fresh_db_is_noop(engine):
    # conftest 的 engine 夹具已对全新库 create_all，迁移应跳过全部补列动作
    async with engine.connect() as conn:
        applied = await conn.run_sync(apply_schema_upgrades)
        assert not any("ADD COLUMN" in action for action in applied)
        assert "uq_dashboard_users_ldap_username" in await conn.run_sync(_index_names)


_NULLABLE_PASSWORD_HASH_INSERT_SQL = (
    "INSERT INTO dashboard_users (username, password_hash, role, is_active, "
    "must_change_password) VALUES (:username, :password_hash, 'user', 1, 0)"
)


def test_migration_rebuilds_legacy_table_to_nullable_password_hash(tmp_path):
    """password_hash 仍为 NOT NULL 的存量库：迁移按模型重建表解除非空约束。

    旧行数据必须保全（字段值原样、auth_source 回填 local），新表须允许
    password_hash 为 NULL（绑定迁移语义），且 username 唯一约束仍生效。
    """
    legacy_hash = "x" * 60
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as conn:
        conn.execute(text(_TENANTS_CREATE_SQL))
        conn.execute(text(_LEGACY_CREATE_SQL))
        conn.execute(
            text(_LEGACY_INSERT_SQL),
            {"username": "legacy_user", "password_hash": legacy_hash, "role": "user"},
        )
    legacy_engine.dispose()

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        applied = apply_schema_upgrades(conn)
        assert any("rebuild" in action for action in applied)

        # 重建后的表与模型零漂移：password_hash 可空（与模型列定义一致）
        columns = {c["name"]: c["nullable"] for c in inspect(conn).get_columns("dashboard_users")}
        assert columns["password_hash"] is True

        # 旧行数据保全：字段值原样、auth_source 按 ADD COLUMN 默认值回填 local
        row = conn.execute(text(
            "SELECT username, role, is_active, auth_source, password_hash "
            "FROM dashboard_users WHERE username = 'legacy_user'"
        )).one()
        assert row.username == "legacy_user" and row.role == "user"
        assert row.is_active == 1 and row.auth_source == "local"
        assert row.password_hash == legacy_hash

        # 新表允许 password_hash 为 NULL 的行（LDAP 绑定后的形态）
        conn.execute(
            text(_NULLABLE_PASSWORD_HASH_INSERT_SQL),
            {"username": "bound_user", "password_hash": None},
        )
    engine.dispose()

    # username 唯一约束在重建后仍生效（独立事务：SQLite 驱动对 DDL 隐式提交，
    # 事务中途 rollback 会让迁移的 DDL 部分提交、DML 部分回滚）
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        try:
            conn.execute(
                text(_NULLABLE_PASSWORD_HASH_INSERT_SQL),
                {"username": "legacy_user", "password_hash": "y" * 60},
            )
        except IntegrityError:
            conn.rollback()
        else:
            raise AssertionError("重复 username 未触发唯一约束")
    engine.dispose()

    # 幂等：第二次迁移不再重建
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        applied_again = apply_schema_upgrades(conn)
        assert not any("rebuild" in action for action in applied_again)
        assert not any("ADD COLUMN" in action for action in applied_again)
    engine.dispose()


def _fk_on_engine(path) -> "create_engine":
    """与 app.core.db 同款：连接级开启外键约束的引擎。"""
    engine = create_engine(path)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_migration_rebuild_preserves_audit_actor_during_fk_actions(tmp_path):
    """R2：重建期间关闭外键动作，audit_logs.actor_user_id 归因原样保留。

    生产引擎连接级开启 PRAGMA foreign_keys；若重建未按官方规程先关闭外键，
    DROP 父表的隐式 DELETE 会把子表 actor_user_id 一次性置空，审计归因丢失。
    """
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as conn:
        conn.execute(text(_LEGACY_CREATE_SQL))
        conn.execute(
            text(_LEGACY_INSERT_SQL),
            {"username": "legacy_user", "password_hash": "x" * 60, "role": "user"},
        )
        # 最小 audit_logs：与 AuditLog 模型一致的外键形态（ondelete=SET NULL）
        conn.execute(text(
            "CREATE TABLE audit_logs ("
            " id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,"
            " actor_user_id INTEGER REFERENCES dashboard_users (id) ON DELETE SET NULL,"
            " actor_name VARCHAR(64) NOT NULL,"
            " action VARCHAR(64) NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO audit_logs (actor_user_id, actor_name, action)"
            " VALUES ((SELECT id FROM dashboard_users WHERE username = 'legacy_user'),"
            " 'legacy_user', 'auth.login.success')"
        ))
    legacy_engine.dispose()

    engine = _fk_on_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        applied = apply_schema_upgrades(conn)
        assert any("rebuild" in action for action in applied)
        # 官方规程收尾的 foreign_key_check：整库无外键违规
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        # 归因保全：actor_user_id 原样指向重建后的 legacy 用户行（id 不变）
        audit = conn.execute(text(
            "SELECT actor_user_id, actor_name FROM audit_logs"
        )).one()
        user_id = conn.execute(text(
            "SELECT id FROM dashboard_users WHERE username = 'legacy_user'"
        )).scalar_one()
        assert audit.actor_user_id == user_id
        assert audit.actor_name == "legacy_user"

    # 连接池化复用：connect 事件不会重放，外键必须由迁移显式恢复为 ON
    with engine.begin() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    engine.dispose()
