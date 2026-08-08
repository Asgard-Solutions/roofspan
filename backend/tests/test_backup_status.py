"""Tests for /api/admin/backup-status endpoint (RBAC + shape)."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-mono-deploy.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def owner_token():
    r = _login(OWNER_EMAIL, OWNER_PASSWORD)
    assert r.status_code == 200, f"Owner login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def sales_user(owner_token):
    """Create a sales user for RBAC test."""
    unique = uuid.uuid4().hex[:8]
    email = f"test_sales_{unique}@example.com"
    password = "TestSales#2026"
    payload = {
        "email": email,
        "full_name": "TEST Sales User",
        "role": "sales",
        "password": password,
    }
    r = requests.post(
        f"{BASE_URL}/api/users",
        json=payload,
        headers={"Authorization": f"Bearer {owner_token}"},
        timeout=15,
    )
    assert r.status_code in (200, 201), f"Create sales user failed: {r.status_code} {r.text}"
    user = r.json()
    yield {"email": email, "password": password, "id": user.get("id")}
    # cleanup best-effort
    try:
        requests.delete(
            f"{BASE_URL}/api/users/{user.get('id')}",
            headers={"Authorization": f"Bearer {owner_token}"},
            timeout=10,
        )
    except Exception:
        pass


class TestBackupStatusRBAC:
    def test_unauthenticated_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/backup-status", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def test_owner_gets_200_with_expected_shape(self, owner_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/backup-status",
            headers={"Authorization": f"Bearer {owner_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ("local_backup", "offsite_copy", "offsite_restore_drill", "local_backup_count", "backup_dir"):
            assert key in data, f"missing key {key} in {data}"
        for section in ("local_backup", "offsite_copy", "offsite_restore_drill"):
            sec = data[section]
            assert set(("status", "ok", "timestamp")).issubset(sec.keys()), f"{section} missing subkeys"
            assert isinstance(sec["ok"], bool)
        assert isinstance(data["local_backup_count"], int)
        assert isinstance(data["backup_dir"], str)

    def test_sales_user_forbidden_403(self, sales_user):
        r = _login(sales_user["email"], sales_user["password"])
        assert r.status_code == 200, f"sales login failed: {r.text}"
        token = r.json()["access_token"]
        r2 = requests.get(
            f"{BASE_URL}/api/admin/backup-status",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        assert r2.status_code == 403, f"expected 403 for sales, got {r2.status_code} {r2.text}"


class TestRegressionSanity:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200

    def test_users_list_owner(self, owner_token):
        r = requests.get(
            f"{BASE_URL}/api/users",
            headers={"Authorization": f"Bearer {owner_token}"},
            timeout=15,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_materials_list_owner(self, owner_token):
        r = requests.get(
            f"{BASE_URL}/api/materials",
            headers={"Authorization": f"Bearer {owner_token}"},
            timeout=15,
        )
        assert r.status_code == 200
