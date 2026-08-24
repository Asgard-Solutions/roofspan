"""ABC Supply environment switch (Sandbox <-> Production) safety: switching env must clear the
environment-specific app credentials + tokens and force a clean reconnect."""
import os

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


def _cfg(headers):
    return requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=headers, timeout=30).json()


def test_switch_env_clears_credentials_and_forces_reconnect(owner_headers):
    h = owner_headers
    # Start on sandbox with a client id.
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h,
                 json={"environment": "sandbox", "client_id": "sandbox-client-xyz"}, timeout=30)
    before = _cfg(h)
    assert before["environment"] == "sandbox"
    assert before["has_client_id"] is True

    # Switch to production -> credentials cleared, status not_connected.
    r = requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h,
                     json={"environment": "production"}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    after = r.json()
    assert after["environment"] == "production"
    assert after["has_client_id"] is False
    assert after["status"] == "not_connected"

    # Rejects invalid environment.
    bad = requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h,
                       json={"environment": "staging"}, timeout=30)
    assert bad.status_code == 422

    # Restore sandbox for other suites.
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h, json={"environment": "sandbox"}, timeout=30)


def test_saving_same_env_does_not_wipe_client_id(owner_headers):
    h = owner_headers
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h,
                 json={"environment": "sandbox", "client_id": "keep-me-123"}, timeout=30)
    # Re-save same env with no client_id in payload -> existing client id preserved.
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=h,
                 json={"environment": "sandbox", "webhook_public_url": "https://example.com/wh"}, timeout=30)
    st = _cfg(h)
    assert st["environment"] == "sandbox"
    assert st["has_client_id"] is True
