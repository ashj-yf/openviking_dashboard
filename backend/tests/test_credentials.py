"""我的凭证：打码、显式暴露审计、自助重签。"""
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.models import AuditLog, KeyRecord
from app.services.credential_service import mask_key


def test_mask_rules():
    assert mask_key("1234567890abcd") == "1234" + "*" * 6 + "abcd"  # 14 位：留 4/4
    assert mask_key("12345678") == "*" * 8                          # <=8 全打码
    assert mask_key("123456789") == "1234*6789"                     # 9 位：1 颗星（末 4 位 6789）
    assert mask_key("x" * 30) == "xxxx" + "*" * 12 + "xxxx"        # 星号上限 12


async def test_credential_view_masked(
    client, db, make_user, make_tenant, auth_headers
):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="ov-secret-key-1234567")
    db.add(KeyRecord(tenant_id=t.id, dashboard_user_id=u.id, ov_user_id="alice",
                     key_kind="user", key_hint="ov-secre", seed_used=False))
    await db.commit()
    r = await client.get("/api/v1/credentials", headers=auth_headers(u))
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == "acme"
    assert body["ov_user_id"] == "alice"
    assert body["has_key"] is True
    assert "ov-secret-key-1234567" not in r.text
    assert body["key_masked"] == "ov-s" + "*" * 12 + "4567"
    assert body["key_hint"] == "ov-secre"
    assert body["seed_used"] is False


async def test_platform_admin_credentials_conflict(client, make_user, auth_headers):
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    assert (await client.get("/api/v1/credentials",
                              headers=auth_headers(admin))).status_code == 409


async def test_pending_key_view_shape(client, make_user, make_tenant, auth_headers):
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin",
                          tenant=t, ov_user_id="boss")  # 无 key
    r = await client.get("/api/v1/credentials", headers=auth_headers(ta))
    assert r.status_code == 200
    body = r.json()
    assert body["has_key"] is False
    assert body["key_masked"] is None


async def test_reveal_and_copy_return_plaintext_with_distinct_audit(
    client, db, make_user, make_tenant, auth_headers
):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="ov-secret-key-1234567")
    r1 = await client.post("/api/v1/credentials/reveal", headers=auth_headers(u))
    assert r1.status_code == 200
    assert r1.json()["key"] == "ov-secret-key-1234567"
    r2 = await client.post("/api/v1/credentials/copy", headers=auth_headers(u))
    assert r2.status_code == 200
    assert r2.json()["key"] == "ov-secret-key-1234567"
    actions = [a.action for a in (await db.scalars(select(AuditLog))).all()]
    assert actions.count("key.view") == 1
    assert actions.count("key.copy") == 1


async def test_reveal_pending_conflict(client, make_user, make_tenant, auth_headers):
    t = await make_tenant("acme")
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t, ov_user_id="boss")
    assert (await client.post("/api/v1/credentials/reveal",
                               headers=auth_headers(ta))).status_code == 409


async def test_credentials_require_auth(client):
    assert (await client.get("/api/v1/credentials")).status_code == 401


async def test_self_regenerate_rotates(client, db, make_user, make_tenant,
                                        auth_headers, ov_calls):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="old-key-12345678")
    ov_calls["responses"].append((200, {"key": "brand-new-key-9999"}))
    r = await client.post(
        "/api/v1/credentials/regenerate", json={"seed": "mine"}, headers=auth_headers(u)
    )
    assert r.status_code == 200
    assert r.json()["key"] == "brand-new-key-9999"
    assert r.json()["seed_used"] is True
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "brand-new-key-9999"
    assert any(a.action == "key.regenerate" for a in
               (await db.scalars(select(AuditLog))).all())
    assert ov_calls["calls"][0]["path"] == "/api/v1/admin/accounts/acme/users/alice/key"
    assert ov_calls["calls"][0]["body"] == {"seed": "mine"}


async def test_self_regenerate_ov_failure_keeps_old(
    client, db, make_user, make_tenant, auth_headers, ov_calls
):
    t = await make_tenant("acme")
    u = await make_user("alice", "Passw0rd!", "user", tenant=t, ov_user_id="alice",
                         ov_key="old-key-12345678")
    ov_calls["responses"].append((500, {"detail": "boom"}))
    r = await client.post("/api/v1/credentials/regenerate", json={},
                           headers=auth_headers(u))
    assert r.status_code == 500
    await db.refresh(u)
    assert decrypt_secret(u.ov_user_key_encrypted) == "old-key-12345678"


async def test_keys_never_leak_across_read_endpoints(
    client, make_user, make_tenant, auth_headers
):
    """Review Focus 1：列表/详情/打码视图中 grep 不到 user key 与 root key。"""
    t = await make_tenant("acme")
    admin = await make_user("rootadmin", "Admin#12345", "admin")
    secret = "leak-check-key-1234567"
    ta = await make_user("boss", "Passw0rd!", "team_admin", tenant=t,
                          ov_user_id="boss", ov_role="admin", ov_key=secret)
    await make_user("alice", "Passw0rd!", "user", tenant=t,
                     ov_user_id="alice", ov_role="user", ov_key=secret)
    bodies = []
    for method, path in [
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/tenants"),
        ("GET", f"/api/v1/tenants/{t.id}"),
    ]:
        r = await client.request(method, path, headers=auth_headers(admin))
        assert r.status_code == 200, (path, r.status_code, r.text)
        bodies.append(r.text)
    r = await client.get("/api/v1/credentials", headers=auth_headers(ta))
    assert r.status_code == 200
    bodies.append(r.text)
    for blob in bodies:
        assert secret not in blob
        assert "test-root-key" not in blob
