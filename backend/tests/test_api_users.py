"""用户开通、列表与生命周期管理路由。"""
import pytest
# Task 5 追加：from app.core.crypto import decrypt_secret
# Task 5 追加：from app.services.auth_service import authenticate
# Task 6 追加：from sqlalchemy import select
# Task 6 追加：from app.models import AuditLog, DashboardUser, KeyRecord


async def test_create_user_api_and_no_key_in_response(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    t = await make_tenant("acme")
    ov_calls["responses"].extend([
        (200, {"user_id": "carol"}),
        (200, {"key": "user-key-1234567890"}),
    ])
    r = await client.post(
        "/api/v1/users",
        json={"username": "carol", "password": "Carol#1234", "tenant_id": t.id},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201, r.text
    assert "user-key-1234567890" not in r.text
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users"
    assert ov_calls["calls"][1]["path"] == "/api/v1/admin/accounts/acme/users/carol/key"
    assert all(c["authorization"] == "Bearer test-root-key" for c in ov_calls["calls"])


async def test_user_role_cannot_open_users(client, make_user, make_tenant, auth_headers):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice")
    assert (await client.get("/api/v1/users", headers=auth_headers(u))).status_code == 403
    assert (await client.post("/api/v1/users", json={
        "username": "x", "password": "Xxxx#12345", "tenant_id": t.id,
    }, headers=auth_headers(u))).status_code == 403


async def test_team_admin_cross_tenant_create_forced_scoped(
    client, make_user, make_tenant, auth_headers, ov_calls
):
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t1, ov_user_id="boss")
    ov_calls["responses"].extend([(200, {}), (200, {"key": "k-1234567890ab"})])
    r = await client.post(
        "/api/v1/users",
        json={"username": "x", "password": "Xxxx#12345", "tenant_id": t2.id},
        headers=auth_headers(ta),
    )
    assert r.status_code == 201
    assert r.json()["tenant_id"] == t1.id


async def test_list_scoping_and_shape(
    client, make_user, make_tenant, auth_headers
):
    platform = await make_user("rootadmin", "Admin#12345", "admin")
    t1 = await make_tenant("acme")
    t2 = await make_tenant("beta")
    await make_user("a1", "Passw0rd!", "user", tenant=t1, ov_user_id="a1", ov_key="key-a-1")
    await make_user("a2", "Passw0rd!", "user", tenant=t1, ov_user_id="a2")
    await make_user("b1", "Passw0rd!", "user", tenant=t2, ov_user_id="b1", ov_key="key-b-1")
    ta = await make_user("boss", "Passw0rd!", "team_admin",
                         tenant=t1, ov_user_id="boss", ov_key="boss-key")

    r = await client.get("/api/v1/users", headers=auth_headers(platform))
    assert r.status_code == 200
    rows = r.json()
    assert {u["username"] for u in rows} == {"rootadmin", "a1", "a2", "b1", "boss"}
    for u in rows:
        assert "ov_user_key_encrypted" not in u
        assert "password_hash" not in u
        assert u["key_state"] in ("current", "pending")
    assert next(u for u in rows if u["username"] == "a1")["key_state"] == "current"
    assert next(u for u in rows if u["username"] == "a2")["key_state"] == "pending"

    r = await client.get("/api/v1/users", headers=auth_headers(ta))
    assert {u["username"] for u in r.json()} == {"a1", "a2", "boss"}

    r = await client.get(
        "/api/v1/users", params={"tenant_id": t2.id}, headers=auth_headers(platform)
    )
    assert {u["username"] for u in r.json()} == {"b1"}
