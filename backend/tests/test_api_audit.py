"""审计日志查询路由：RBAC 范围、筛选、分页、排序与容错解析。"""
from datetime import datetime

from app.models import AuditLog
from app.services import audit_service


async def test_audit_routes_forbidden_for_user(client, make_user, auth_headers):
    viewer = await make_user("plain", "Passw0rd!", "user")
    r = await client.get("/api/v1/audit-logs", headers=auth_headers(viewer))
    assert r.status_code == 403


async def test_audit_list_scoping(client, db, make_user, make_tenant, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t1 = await make_tenant("t1")
    t2 = await make_tenant("t2")
    u1 = await make_user("u1", "Passw0rd!", "user", tenant=t1)
    u2 = await make_user("u2", "Passw0rd!", "user", tenant=t2)
    ta = await make_user("ta", "Passw0rd!", "team_admin", tenant=t1)

    await audit_service.record(
        db, "tenant.create", actor=u1, target_type="tenant", target_id="t1"
    )
    await audit_service.record(
        db, "tenant.create", actor=u2, target_type="tenant", target_id="t2"
    )
    # LDAP 行：无看板账号，actor_user_id 为 NULL
    await audit_service.record(db, "ldap.bind.success", actor_name="ldap-svc")

    # admin 见全部
    r = await client.get("/api/v1/audit-logs", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["total"] == 3

    # team_admin 仅见本团队 actor 的行（不含 t2 与 NULL actor 行）
    r = await client.get("/api/v1/audit-logs", headers=auth_headers(ta))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["actor_name"] == "u1"
    assert body["items"][0]["actor_user_id"] == u1.id

    # 删除 actor 用户后 FK SET NULL：team_admin 不再可见，admin 仍可见
    await db.delete(u1)
    await db.commit()
    r = await client.get("/api/v1/audit-logs", headers=auth_headers(ta))
    assert r.json()["total"] == 0
    r = await client.get("/api/v1/audit-logs", headers=auth_headers(admin))
    body = r.json()
    assert body["total"] == 3
    # u1 的行 SET NULL 后与 LDAP 行一样 actor_user_id 为 NULL，共 2 行
    assert sum(1 for i in body["items"] if i["actor_user_id"] is None) == 2


async def test_audit_filters(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    await audit_service.record(db, "auth.login.success", actor=admin)
    await audit_service.record(db, "tenant.create", actor_name="alice-service")
    # 受控时间行（固定 created_at，用于 start/end 边界断言）
    db.add(
        AuditLog(
            actor_name="bob",
            action="user.disable",
            created_at=datetime(2026, 1, 15, 12, 0, 0),
        )
    )
    await db.commit()

    # action 前缀匹配：auth. 命中 auth.login.success，不命中 tenant.create
    r = await client.get(
        "/api/v1/audit-logs", params={"action": "auth."}, headers=auth_headers(admin)
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "auth.login.success"

    # actor 模糊（contains）
    r = await client.get(
        "/api/v1/audit-logs", params={"actor": "roo"}, headers=auth_headers(admin)
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["actor_name"] == "rootadmin"
    r = await client.get(
        "/api/v1/audit-logs", params={"actor": "ali"}, headers=auth_headers(admin)
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["actor_name"] == "alice-service"

    # start 边界（>=，含等号）
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "start": "2026-01-15T12:00:00"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 1
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "start": "2026-01-15T12:00:01"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 0

    # end 边界（<=，含等号）
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "end": "2026-01-15T12:00:00"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 1
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "end": "2026-01-15T11:59:59"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 0


async def test_audit_pagination(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    for _ in range(25):
        await audit_service.record(db, "auth.login.success", actor=admin)

    r = await client.get(
        "/api/v1/audit-logs",
        params={"page": 2, "page_size": 20},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 25
    assert body["page"] == 2
    assert body["page_size"] == 20
    assert len(body["items"]) == 5

    # 恶意分页参数被 schema 拒绝
    r = await client.get(
        "/api/v1/audit-logs", params={"page": 0}, headers=auth_headers(admin)
    )
    assert r.status_code == 422
    r = await client.get(
        "/api/v1/audit-logs", params={"page_size": 101}, headers=auth_headers(admin)
    )
    assert r.status_code == 422


async def test_audit_detail_parse_and_tolerant(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    await audit_service.record(
        db, "tenant.sync", actor=admin, detail={"matched": 3, "missing_local": []}
    )
    # 历史脏数据：detail_json 非 JSON 串不得 500
    db.add(
        AuditLog(actor_name="legacy", action="user.disable", detail_json="not-json")
    )
    await db.commit()

    r = await client.get("/api/v1/audit-logs", headers=auth_headers(admin))
    assert r.status_code == 200
    by_action = {item["action"]: item for item in r.json()["items"]}
    assert by_action["tenant.sync"]["detail"] == {"matched": 3, "missing_local": []}
    assert by_action["user.disable"]["detail"] == {"_raw": "not-json"}


async def test_audit_filters_like_wildcard_is_literal(client, db, make_user, auth_headers):
    """用户输入的 % 按字面匹配（autoescape），不作为 LIKE 通配符。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    await audit_service.record(db, "%export", actor=admin)
    await audit_service.record(db, "auth.login.success", actor=admin)

    # action=%：若 % 被当通配符会命中全部行；字面匹配只命中以 % 开头的行
    r = await client.get(
        "/api/v1/audit-logs", params={"action": "%"}, headers=auth_headers(admin)
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "%export"

    # a%：不命中不含字面 "a%" 前缀的普通行（auth. 开头的行）
    r = await client.get(
        "/api/v1/audit-logs", params={"action": "a%"}, headers=auth_headers(admin)
    )
    assert r.json()["total"] == 0


async def test_audit_filters_tz_aware_normalized_to_utc(client, db, make_user, auth_headers):
    """tz-aware 的 start 与同值 naive 过滤结果一致（tz-aware 归一为 UTC naive）。"""
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    db.add(
        AuditLog(
            actor_name="bob",
            action="user.disable",
            created_at=datetime(2026, 1, 1, 0, 0, 0),
        )
    )
    await db.commit()

    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "start": "2026-01-01T00:00:00Z"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 1
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "start": "2026-01-01T00:00:00"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 1

    # 非 UTC 偏移量按 astimezone(UTC) 归一：+08:00 的零点即 UTC 零点，同样命中
    r = await client.get(
        "/api/v1/audit-logs",
        params={"actor": "bob", "start": "2026-01-01T08:00:00+08:00"},
        headers=auth_headers(admin),
    )
    assert r.json()["total"] == 1


async def test_audit_sorted_desc(client, db, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    for _ in range(3):
        await audit_service.record(db, "auth.login.success", actor=admin)

    r = await client.get("/api/v1/audit-logs", headers=auth_headers(admin))
    items = r.json()["items"]
    assert len(items) == 3
    # created_at 降序；同秒行由 id 兜底降序
    created = [item["created_at"] for item in items]
    ids = [item["id"] for item in items]
    assert created == sorted(created, reverse=True)
    assert ids == sorted(ids, reverse=True)
