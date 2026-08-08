"""Tests for deployment durability: cron backup endpoint + regression sanity."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://roofspan-core.preview.emergentagent.com").rstrip("/")
CRON_SECRET = "rs_cron_9b1f7c2e4a6d8f0b3c5e7a9d1f2b4c6e8a0d2f4b6c8e0a1d3f5b7c9e1a3d5f7"
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASS = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def owner_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASS}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in login response: {data}"
    return token


# --- Cron backup endpoint ---
class TestCronBackup:
    def test_no_auth_returns_401(self):
        r = requests.post(f"{BASE_URL}/api/cron/backup", timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"

    def test_wrong_bearer_returns_401(self):
        r = requests.post(f"{BASE_URL}/api/cron/backup",
                          headers={"Authorization": "Bearer wrong_token_xyz"}, timeout=10)
        assert r.status_code == 401

    def test_correct_bearer_returns_accepted(self):
        r = requests.post(f"{BASE_URL}/api/cron/backup",
                          headers={"Authorization": f"Bearer {CRON_SECRET}"}, timeout=15)
        assert r.status_code in (200, 202), f"Expected 2xx, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("status") == "accepted"
        assert body.get("task") == "db-backup"

    def test_owner_jwt_cannot_be_used_as_cron_bearer(self, owner_token):
        # A normal user JWT must not authorize the cron endpoint
        r = requests.post(f"{BASE_URL}/api/cron/backup",
                          headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
        assert r.status_code == 401


# --- Regression sanity ---
class TestRegression:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_auth_me_owner(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("role") == "owner", f"Role not owner: {data}"

    def test_users_list_owner(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/users",
                         headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Accept list or {items:[...]}
        items = body if isinstance(body, list) else body.get("items", body.get("users", []))
        assert isinstance(items, list)

    def test_materials_list(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/materials",
                         headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        items = body if isinstance(body, list) else body.get("items", body.get("materials", []))
        assert isinstance(items, list)


# --- Security sanity ---
class TestSecurity:
    def test_unauth_users_401(self):
        r = requests.get(f"{BASE_URL}/api/users", timeout=10)
        assert r.status_code == 401

    def test_integrations_masked(self, owner_token):
        r = requests.get(f"{BASE_URL}/api/integrations",
                         headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
        assert r.status_code == 200
        body = r.json()
        providers = body if isinstance(body, list) else body.get("items", body.get("providers", []))
        assert isinstance(providers, list)
        for p in providers:
            # Must never expose plaintext secret
            assert "secret" not in p or p.get("secret") in (None, "", "***"), f"Plaintext secret leaked: {p}"
            assert "api_key" not in p or p.get("api_key") in (None, "", "***"), f"Plaintext api_key leaked: {p}"
            # Must include masked indicators
            assert "has_secret" in p or "secret_masked" in p, f"Missing masked indicators: {p}"
