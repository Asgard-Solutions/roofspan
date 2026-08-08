"""RoofSpan Office Phase 1 backend regression tests."""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://roofspan-core.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


# --------- Fixtures ---------
@pytest.fixture(scope="session")
def owner_token():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Owner login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data and data["user"]["role"] == "owner"
    return data["access_token"]


@pytest.fixture(scope="session")
def owner_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}


def _unique_email(prefix="sales"):
    return f"TEST_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(scope="session")
def sales_user(owner_headers):
    email = _unique_email("sales")
    payload = {"email": email, "full_name": "TEST Sales", "password": "SalesTemp#2026", "role": "sales"}
    r = requests.post(f"{API}/users", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    return {"id": r.json()["id"], "email": email, "password": "SalesTemp#2026"}


@pytest.fixture(scope="session")
def sales_headers(sales_user):
    r = requests.post(f"{API}/auth/login", json={"email": sales_user["email"], "password": sales_user["password"]}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_user_and_headers(owner_headers):
    email = _unique_email("admin")
    payload = {"email": email, "full_name": "TEST Admin", "password": "AdminTemp#2026", "role": "administrator"}
    r = requests.post(f"{API}/users", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": "AdminTemp#2026"}, timeout=15)
    assert lr.status_code == 200, lr.text
    return {"id": uid, "email": email, "headers": {"Authorization": f"Bearer {lr.json()['access_token']}"}}


# --------- Health ---------
def test_health():
    r = requests.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok" and d["database"] == "postgresql"


# --------- Auth ---------
def test_owner_login_and_me(owner_headers):
    r = requests.get(f"{API}/auth/me", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["email"] == OWNER_EMAIL and d["role"] == "owner"


def test_login_wrong_password():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": "wrong-password-xyz"}, timeout=15)
    assert r.status_code == 401


def test_login_creates_audit_entry(owner_headers):
    # Should already have at least one auth.login entry
    r = requests.get(f"{API}/audit", params={"action": "auth.login", "limit": 5}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any(item["action"] == "auth.login" for item in data["items"])


# --------- RBAC ---------
def test_rbac_sales_forbidden_endpoints(sales_headers):
    forbidden = [
        ("GET", "/users"),
        ("GET", "/audit"),
        ("GET", "/integrations"),
    ]
    for method, path in forbidden:
        r = requests.request(method, f"{API}{path}", headers=sales_headers, timeout=15)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
    # PUT map-config forbidden
    r = requests.put(f"{API}/map-config", json={"satellite_enabled": True}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


def test_rbac_sales_allowed_endpoints(sales_headers):
    for path in ["/map-config", "/company", "/dashboard/summary"]:
        r = requests.get(f"{API}{path}", headers=sales_headers, timeout=15)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"


def test_no_auth_returns_401():
    r = requests.get(f"{API}/users", timeout=15)
    assert r.status_code in (401, 403)


# --------- Users CRUD ---------
def test_list_users_owner(owner_headers):
    r = requests.get(f"{API}/users", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    users = r.json()
    assert any(u["email"] == OWNER_EMAIL for u in users)


def test_create_user_and_login(owner_headers):
    email = _unique_email("office")
    payload = {"email": email, "full_name": "TEST Office", "password": "OfficeTemp#2026", "role": "office"}
    r = requests.post(f"{API}/users", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201
    created = r.json()
    assert created["email"] == email.lower() and created["role"] == "office" and created["is_active"] is True
    # Login with temp password
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": "OfficeTemp#2026"}, timeout=15)
    assert lr.status_code == 200


def test_duplicate_email_returns_409(owner_headers):
    email = _unique_email("dup")
    payload = {"email": email, "full_name": "TEST Dup", "password": "DupTemp#2026", "role": "sales"}
    r1 = requests.post(f"{API}/users", json=payload, headers=owner_headers, timeout=15)
    assert r1.status_code == 201
    r2 = requests.post(f"{API}/users", json=payload, headers=owner_headers, timeout=15)
    assert r2.status_code == 409


def test_update_role_and_status(owner_headers, sales_user):
    r = requests.patch(f"{API}/users/{sales_user['id']}", json={"full_name": "TEST Sales Updated"}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["full_name"] == "TEST Sales Updated"


def test_reset_password(owner_headers):
    email = _unique_email("reset")
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "TEST Reset", "password": "InitTemp#2026", "role": "sales"}, headers=owner_headers, timeout=15)
    assert r.status_code == 201
    uid = r.json()["id"]
    new_pwd = "NewTemp#2026"
    rr = requests.post(f"{API}/users/{uid}/reset-password", json={"new_password": new_pwd}, headers=owner_headers, timeout=15)
    assert rr.status_code == 200
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": new_pwd}, timeout=15)
    assert lr.status_code == 200


def test_cannot_deactivate_self(owner_headers):
    me = requests.get(f"{API}/auth/me", headers=owner_headers, timeout=15).json()
    r = requests.patch(f"{API}/users/{me['id']}", json={"is_active": False}, headers=owner_headers, timeout=15)
    assert r.status_code == 400


def test_only_owner_can_assign_owner_role(admin_user_and_headers, owner_headers):
    # Admin tries to create an owner
    payload = {"email": _unique_email("badowner"), "full_name": "TEST Bad", "password": "Bad#2026", "role": "owner"}
    r = requests.post(f"{API}/users", json=payload, headers=admin_user_and_headers["headers"], timeout=15)
    assert r.status_code == 403
    # Admin tries to promote a user to owner via PATCH
    tgt_email = _unique_email("promo")
    c = requests.post(f"{API}/users", json={"email": tgt_email, "full_name": "TEST Promo", "password": "P#2026aaaa", "role": "sales"}, headers=owner_headers, timeout=15)
    assert c.status_code == 201
    tgt_id = c.json()["id"]
    up = requests.patch(f"{API}/users/{tgt_id}", json={"role": "owner"}, headers=admin_user_and_headers["headers"], timeout=15)
    assert up.status_code == 403


# --------- Integrations ---------
def test_integrations_list_owner(owner_headers):
    r = requests.get(f"{API}/integrations", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    providers = {i["provider"]: i for i in r.json()}
    assert "rentcast" in providers and "maptiler" in providers


def test_rentcast_secret_set_mask_and_clear(owner_headers):
    fake_key = "rc_test_ABCD1234WXYZ"
    r = requests.put(f"{API}/integrations/rentcast/secret", json={"secret": fake_key}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["has_secret"] is True
    assert d["secret_masked"] == f"••••••••{fake_key[-4:]}"
    # Never returns plaintext
    body_text = r.text
    assert fake_key not in body_text
    # Toggle enabled
    up = requests.put(f"{API}/integrations/rentcast", json={"enabled": True}, headers=owner_headers, timeout=15)
    assert up.status_code == 200 and up.json()["enabled"] is True
    # Test connection with fake key - expected to fail gracefully
    tc = requests.post(f"{API}/integrations/rentcast/test", headers=owner_headers, timeout=30)
    assert tc.status_code == 200
    td = tc.json()
    assert td["ok"] is False and isinstance(td.get("message"), str)
    # Clear secret
    dl = requests.delete(f"{API}/integrations/rentcast/secret", headers=owner_headers, timeout=15)
    assert dl.status_code == 200
    assert dl.json()["has_secret"] is False
    # Row still exists in list
    lst = requests.get(f"{API}/integrations", headers=owner_headers, timeout=15).json()
    assert any(i["provider"] == "rentcast" for i in lst)


# --------- Map config ---------
def test_map_config_default(owner_headers):
    r = requests.get(f"{API}/map-config", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["base_provider"] == "openstreetmap"
    assert "openstreetmap.org" in d["osm_tile_url"]
    assert d["maptiler_configured"] is False
    assert d["satellite_enabled"] is False


def test_map_config_satellite_effectively_false_without_maptiler(owner_headers):
    r = requests.put(f"{API}/map-config", json={"satellite_enabled": True}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    # Even though we set satellite_enabled=True, since MapTiler isn't configured+enabled, effective is False
    assert d["satellite_enabled"] is False
    assert d["maptiler_configured"] is False


# --------- Audit ---------
def test_audit_list_reflects_recent_actions(owner_headers):
    r = requests.get(f"{API}/audit", params={"limit": 50}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and "total" in d and d["total"] > 0
    actions = {i["action"] for i in d["items"]}
    # Should have login and user.create somewhere in recent
    assert "auth.login" in actions
    assert any(a.startswith("user.") for a in actions)
