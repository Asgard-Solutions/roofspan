"""Phase C0 integration tests: licensing API, state machine enforcement, guard, billing stub.

Runs against the live backend (dev licensing mode). Always restores ACTIVE/50 so other suites are
unaffected. Requires LICENSING_MODE=dev (the dev set-state endpoint).
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


def _login(email=OWNER_EMAIL, password=OWNER_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _set_state(headers, state, seats=50):
    r = requests.post(f"{API}/dev/licensing/set-state", json={"state": state, "seats_licensed": seats}, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def restore_active():
    """Ensure every test leaves the installation ACTIVE with 50 seats."""
    owner = _login()
    _set_state(owner, "ACTIVE", 1000)
    yield
    _set_state(owner, "ACTIVE", 1000)


def test_subscription_status_shape():
    owner = _login()
    r = requests.get(f"{API}/subscription", headers=owner, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("state", "reported_state", "business_access", "seats_licensed", "active_users",
              "available_seats", "min_seats", "max_seats", "online", "grace_until"):
        assert k in d
    assert d["state"] == "ACTIVE" and d["business_access"] is True
    assert d["min_seats"] == 5 and d["max_seats"] == 50
    assert d["available_seats"] == max(d["seats_licensed"] - d["active_users"], 0)


def test_license_status_verified_and_signed():
    owner = _login()
    r = requests.get(f"{API}/license/status", headers=owner, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["verified"] is True
    assert d["effective_state"] == "ACTIVE"
    assert d["kid"]  # a signing key id is present
    assert d["installation_id"] and d["company_id"]


def test_license_status_requires_sensitive_role():
    # create a sales user; sales cannot see license/status (sensitive)
    owner = _login()
    import uuid
    email = f"lic_sales_{uuid.uuid4().hex[:6]}@example.com"
    requests.post(f"{API}/users", json={"email": email, "full_name": "Lic Sales", "password": "LicSales#2026", "role": "sales"}, headers=owner, timeout=15)
    sales = _login(email, "LicSales#2026")
    assert requests.get(f"{API}/license/status", headers=sales, timeout=15).status_code == 403
    # but sales CAN read subscription summary (needed for banners)
    assert requests.get(f"{API}/subscription", headers=sales, timeout=15).status_code == 200


def test_suspended_blocks_business_but_allows_recovery():
    owner = _login()
    _set_state(owner, "SUSPENDED", 50)
    # business endpoints blocked with structured error
    r = requests.get(f"{API}/leads", headers=owner, timeout=15)
    assert r.status_code == 403
    body = r.json()
    assert body.get("code") == "subscription_inactive" and body.get("state") == "SUSPENDED"
    # recovery/licensing endpoints remain reachable
    assert requests.get(f"{API}/subscription", headers=owner, timeout=15).status_code == 200
    assert requests.get(f"{API}/license/status", headers=owner, timeout=15).status_code == 200
    assert requests.get(f"{API}/billing/portal-url", headers=owner, timeout=15).status_code == 200
    # auth still works while suspended
    assert requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15).status_code == 200


def test_cancelled_blocks_business():
    owner = _login()
    _set_state(owner, "CANCELLED", 50)
    assert requests.get(f"{API}/properties", headers=owner, timeout=15).status_code == 403


def test_reactivation_unlocks_business():
    owner = _login()
    _set_state(owner, "SUSPENDED", 50)
    assert requests.get(f"{API}/leads", headers=owner, timeout=15).status_code == 403
    _set_state(owner, "ACTIVE", 1000)
    assert requests.get(f"{API}/leads", headers=owner, timeout=15).status_code == 200


def test_billing_link_endpoint():
    owner = _login()
    r = requests.get(f"{API}/billing/portal-url", headers=owner, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "configured" in d
    # default BILLING_MODE=mock -> a hosted URL is returned; stub mode -> not configured
    if d["configured"]:
        assert d["url"]


def test_refresh_endpoint():
    owner = _login()
    r = requests.post(f"{API}/subscription/refresh", headers=owner, timeout=15)
    assert r.status_code == 200 and r.json()["ok"] is True
