"""团队读侧路由：RBAC、形状与降级。"""
import pytest
from sqlalchemy import select

from app.models import AuditLog, DashboardUser, KeyRecord, Tenant


@pytest.mark.parametrize("role", ["team_admin", "user"])
async def test_tenant_routes_forbidden_for_non_admin(
    client, make_user, auth_headers, role
):
    tenant = {"ov_account_id": "acme", "admin_user_id": "boss"}
    actor = await make_user("me", "Passw0rd!", role, tenant=tenant, ov_user_id="me")
    r = await client.get("/api/v1/tenants", headers=auth_headers(actor))
    assert r.status_code == 403


async def test_list_tenants_api(client, db, make_user, make_tenant, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme", display_name="甲")
    await make_user("a1", "Passw0rd!", "user", tenant=t, ov_user_id="a1")
    r = await client.get("/api/v1/tenants", headers=auth_headers(admin))
    assert r.status_code == 200
    item = r.json()[0]
    assert item["account_id"] == "acme"
    assert item["user_count"] == 1
    assert "ov_account" not in item  # 列表项不含 OV 聚合区


async def test_detail_api_degrades_200(client, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov_calls["responses"].extend([(502, {"detail": "bad"})] * 3)
    r = await client.get(f"/api/v1/tenants/{t.id}", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["ov_account"] is None
    assert body["configuration"] is None
    assert body["settings"] is None
    assert body["ov_error"]


async def test_detail_api_404(client, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    r = await client.get("/api/v1/tenants/9999", headers=auth_headers(admin))
    assert r.status_code == 404


async def test_patch_and_sync_api(client, make_user, make_tenant, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    r = await client.patch(
        f"/api/v1/tenants/{t.id}",
        json={"display_name": "新名", "remark": "备注"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "新名"

    ov_calls["responses"].append((200, {"users": [{"user_id": "ghost", "role": "user"}]}))
    r = await client.post(f"/api/v1/tenants/{t.id}/sync", headers=auth_headers(admin))
    assert r.status_code == 200
    report = r.json()
    assert report["ov_user_count"] == 1
    assert report["missing_local"][0]["ov_user_id"] == "ghost"
    assert report["local_user_count"] == 0


async def test_anonymous_rejected(client):
    assert (await client.get("/api/v1/tenants")).status_code == 401


async def test_create_tenant_full_chain(client, db, make_user, auth_headers, ov_calls):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ov_calls["responses"].append((200, {"account_id": "acme", "admin_key": "ak-secret-1234"}))
    r = await client.post(
        "/api/v1/tenants",
        json={
            "account_id": "acme",
            "admin_user_id": "boss",
            "admin_username": "bosslogin",
            "admin_password": "Boss#12345",
            "display_name": "甲团队",
        },
        headers=auth_headers(admin),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["account_id"] == "acme"
    assert body["team_admin_username"] == "bosslogin"
    assert body["key_provisioned"] is True

    call = ov_calls["calls"][0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/v1/admin/accounts"
    assert call["body"]["account_id"] == "acme"
    assert call["body"]["admin_user_id"] == "boss"
    assert call["authorization"] == "Bearer test-root-key"
    assert "test-root-key" not in str(call["body"])

    # 响应不得泄漏初始密码与 key
    assert "ak-secret-1234" not in r.text
    assert "Boss#12345" not in r.text

    tenant = (await db.scalars(select(Tenant))).one()
    assert tenant.ov_account_id == "acme"
    actions = {a.action for a in (await db.scalars(select(AuditLog))).all()}
    assert {"tenant.create", "user.create"} <= actions
    create_log = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "user.create")
    )).one()
    assert create_log.actor_user_id == admin.id  # 操作人是平台 admin，不是 anonymous


async def test_created_team_admin_is_activated_and_key_stored(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    full_key = "ak-x0001-7c92-4f5a0-8b21"  # 非重复模式，前 8 位可稳定辨识
    ov_calls["responses"].append((200, {"account_id": "acme", "admin": {"key": full_key}}))
    r = await client.post(
        "/api/v1/tenants",
        json={"account_id": "acme", "admin_user_id": "boss",
              "admin_username": "bosslogin", "admin_password": "Boss#12345"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    ta = (await db.scalars(select(DashboardUser).where(DashboardUser.role == "team_admin"))).one()
    assert ta.is_active is True            # 初始 team_admin 允许先登录改密
    assert ta.must_change_password is True
    assert ta.ov_role == "admin"
    assert ta.ov_user_id == "boss"
    assert ta.ov_user_key_encrypted is not None
    rec = (await db.scalars(select(KeyRecord))).one()
    assert rec.is_current is True
    assert rec.key_kind == "admin"
    assert rec.key_hint == full_key[:8]
    assert len(rec.key_hint) == 8
    assert full_key not in rec.key_hint  # 8 位 hint 容不下完整 key
    assert full_key not in r.text


async def test_create_tenant_without_admin_key_marks_pending(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ov_calls["responses"].append((200, {"account_id": "acme"}))  # 响应里没有 key
    r = await client.post(
        "/api/v1/tenants",
        json={"account_id": "acme", "admin_user_id": "boss",
              "admin_username": "bosslogin", "admin_password": "Boss#12345"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    assert r.json()["key_provisioned"] is False
    ta = (await db.scalars(select(DashboardUser).where(DashboardUser.role == "team_admin"))).one()
    assert ta.is_active is True
    assert ta.ov_user_key_encrypted is None


async def test_create_tenant_duplicate_local_blocked(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    await make_tenant("acme")
    r = await client.post(
        "/api/v1/tenants",
        json={"account_id": "acme", "admin_user_id": "boss",
              "admin_username": "boss2", "admin_password": "Boss#12345"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 409
    assert ov_calls["calls"] == []  # 本地重复不触达 OV


async def test_create_tenant_ov_conflict_passthrough(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ov_calls["responses"].append((409, {"detail": "account exists"}))
    r = await client.post(
        "/api/v1/tenants",
        json={"account_id": "acme", "admin_user_id": "boss",
              "admin_username": "bosslogin", "admin_password": "Boss#12345"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 409
    assert r.json()["ov_status"] == 409
    assert (await db.scalars(select(Tenant))).all() == []  # OV 失败本地零写入


async def test_seed_passthrough_but_not_audited(
    client, db, make_user, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    ov_calls["responses"].append((200, {"account_id": "acme", "admin_key": "ak-01234567"}))
    r = await client.post(
        "/api/v1/tenants",
        json={"account_id": "acme", "admin_user_id": "boss",
              "admin_username": "bosslogin", "admin_password": "Boss#12345",
              "seed": "deterministic-seed-value"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    assert ov_calls["calls"][0]["body"]["seed"] == "deterministic-seed-value"
    logs = (await db.scalars(select(AuditLog))).all()
    blob = " ".join(log.detail_json or "" for log in logs)
    assert "deterministic-seed-value" not in blob


async def test_delete_tenant_requires_confirm(client, make_user, make_tenant, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    r = await client.request(
        "DELETE", f"/api/v1/tenants/{t.id}", json={}, headers=auth_headers(admin)
    )
    assert r.status_code == 400


async def test_delete_tenant_cascades_and_audits(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    victim = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    ov_calls["responses"].append((200, {}))
    r = await client.request(
        "DELETE",
        f"/api/v1/tenants/{t.id}", json={"confirm": True}, headers=auth_headers(admin)
    )
    assert r.status_code == 204
    assert [c for c in ov_calls["calls"] if c["method"] == "DELETE"][0]["path"] == \
        "/api/v1/admin/accounts/acme"
    assert (await db.scalars(select(Tenant))).all() == []
    assert (await db.scalars(select(DashboardUser).where(DashboardUser.id == victim.id))).all() == []
    actions = {a.action for a in (await db.scalars(select(AuditLog))).all()}
    assert "tenant.delete" in actions


async def test_delete_tenant_ov_refused_local_untouched(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov_calls["responses"].append((403, {"detail": "forbidden"}))
    r = await client.request(
        "DELETE",
        f"/api/v1/tenants/{t.id}", json={"confirm": True}, headers=auth_headers(admin)
    )
    assert r.status_code == 403
    assert await db.get(Tenant, t.id) is not None
