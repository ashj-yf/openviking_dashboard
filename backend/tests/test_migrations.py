"""启动迁移测试：旧库补列 + 唯一索引，新库幂等跳过。"""
from sqlalchemy import create_engine, inspect, text
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


def _index_names(conn) -> set[str]:
    return {ix["name"] for ix in inspect(conn).get_indexes("dashboard_users")}


def _column_names(conn) -> set[str]:
    return {col["name"] for col in inspect(conn).get_columns("dashboard_users")}


def test_migration_on_legacy_db_adds_columns_and_unique_index(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as conn:
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
