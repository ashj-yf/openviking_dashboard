"""团队读侧路由：RBAC、形状与降级。"""
import pytest


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
