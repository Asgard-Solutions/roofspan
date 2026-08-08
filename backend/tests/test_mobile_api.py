"""Mobile API surface tests: idempotency, conflict, photos, RBAC + office regression sanity."""
import os
import uuid
import base64
import io

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-mono-deploy.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"

# 1x1 transparent PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session")
def owner_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Owner login failed: {r.status_code} {r.text}"
    return r.json()["access_token"] if "access_token" in r.json() else r.json().get("token")


@pytest.fixture(scope="session")
def owner_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}"}


@pytest.fixture(scope="session")
def property_id(owner_headers):
    payload = {
        "address_line1": f"TEST_{uuid.uuid4().hex[:8]} Mobile Ln",
        "city": "Denver", "state": "CO", "zip_code": "80202",
        "latitude": 39.7, "longitude": -104.9, "property_type": "SingleFamily",
        "owner_name": "TEST_Owner"
    }
    r = requests.post(f"{BASE_URL}/api/properties", json=payload, headers=owner_headers, timeout=30)
    assert r.status_code == 201, f"Create property failed: {r.status_code} {r.text}"
    return r.json()["id"]


@pytest.fixture(scope="session")
def sales_token(owner_headers):
    """Create a sales user (idempotent-ish) and login."""
    email = f"test_sales_{uuid.uuid4().hex[:6]}@example.com"
    password = "SalesPass#2026"
    r = requests.post(f"{BASE_URL}/api/users", json={
        "email": email, "full_name": "TEST Sales", "password": password, "role": "sales"
    }, headers=owner_headers, timeout=30)
    if r.status_code not in (201, 409):
        pytest.skip(f"Could not create sales user: {r.status_code} {r.text}")
    lr = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert lr.status_code == 200, f"Sales login failed: {lr.text}"
    return lr.json().get("access_token") or lr.json().get("token")


# ---- Visits idempotency ----
class TestIdempotentVisit:
    def test_visit_idempotent_replay(self, owner_headers, property_id):
        key = f"visit-{uuid.uuid4()}"
        notes = f"TEST_visit_{uuid.uuid4().hex[:8]}"
        body = {"property_id": property_id, "outcome": "no_answer", "notes": notes}
        h = {**owner_headers, "Idempotency-Key": key}

        r1 = requests.post(f"{BASE_URL}/api/mobile/visits", json=body, headers=h, timeout=30)
        assert r1.status_code == 201, r1.text
        d1 = r1.json()
        assert d1.get("replayed") is False
        vid = d1["id"]

        r2 = requests.post(f"{BASE_URL}/api/mobile/visits", json=body, headers=h, timeout=30)
        assert r2.status_code == 201, r2.text
        d2 = r2.json()
        assert d2["id"] == vid
        assert d2.get("replayed") is True

        # Verify only one visit with these notes on the property
        pr = requests.get(f"{BASE_URL}/api/properties/{property_id}", headers=owner_headers, timeout=30)
        assert pr.status_code == 200
        visits = [v for v in pr.json().get("visits", []) if v.get("notes") == notes]
        assert len(visits) == 1, f"Expected exactly 1 visit, found {len(visits)}"


# ---- Inspection idempotency + conflict ----
class TestInspectionFlow:
    def test_inspection_idempotent_and_conflict(self, owner_headers, property_id):
        key = f"insp-{uuid.uuid4()}"
        body = {"property_id": property_id, "roof_condition": "fair", "findings": "TEST hail damage"}
        h = {**owner_headers, "Idempotency-Key": key}

        r1 = requests.post(f"{BASE_URL}/api/mobile/inspections", json=body, headers=h, timeout=30)
        assert r1.status_code == 201, r1.text
        d1 = r1.json()
        assert d1.get("replayed") is False
        assert d1.get("if_match"), "Missing if_match token"
        insp_id = d1["id"]
        good_token = d1["if_match"]

        # replay
        r2 = requests.post(f"{BASE_URL}/api/mobile/inspections", json=body, headers=h, timeout=30)
        assert r2.status_code == 201
        assert r2.json()["id"] == insp_id
        assert r2.json().get("replayed") is True

        # stale If-Match -> 409
        stale = "1999-01-01T00:00:00+00:00"
        r3 = requests.patch(
            f"{BASE_URL}/api/mobile/inspections/{insp_id}",
            json={"findings": "updated"},
            headers={**owner_headers, "If-Match": stale}, timeout=30,
        )
        assert r3.status_code == 409, f"Expected 409, got {r3.status_code}: {r3.text}"
        detail = r3.json().get("detail")
        # detail may be dict with message
        assert isinstance(detail, dict) and "changed on the server" in detail.get("message", "").lower(), detail

        # correct If-Match -> 200
        r4 = requests.patch(
            f"{BASE_URL}/api/mobile/inspections/{insp_id}",
            json={"findings": "TEST updated findings"},
            headers={**owner_headers, "If-Match": good_token}, timeout=30,
        )
        assert r4.status_code == 200, r4.text
        assert r4.json()["findings"] == "TEST updated findings"

    def test_idem_key_reuse_different_op(self, owner_headers, property_id):
        """Reusing a visit key on inspections endpoint must 409."""
        key = f"cross-{uuid.uuid4()}"
        # Use as visit key first
        vh = {**owner_headers, "Idempotency-Key": key}
        r1 = requests.post(f"{BASE_URL}/api/mobile/visits", json={"property_id": property_id, "outcome": "no_answer", "notes": "cross-op"}, headers=vh, timeout=30)
        assert r1.status_code == 201, r1.text

        # Reuse on inspections
        r2 = requests.post(f"{BASE_URL}/api/mobile/inspections", json={"property_id": property_id, "roof_condition": "good"}, headers=vh, timeout=30)
        assert r2.status_code == 409, f"Expected 409 for cross-op reuse, got {r2.status_code}: {r2.text}"


# ---- Photos ----
class TestPhotos:
    def test_upload_list_content_and_invalid_type(self, owner_headers, property_id):
        files = {"file": ("test.png", io.BytesIO(PNG_BYTES), "image/png")}
        data = {"record_type": "property", "record_id": property_id, "description": "TEST photo"}
        r = requests.post(f"{BASE_URL}/api/mobile/photos", files=files, data=data, headers=owner_headers, timeout=60)
        assert r.status_code == 201, r.text
        photo = r.json()
        assert photo.get("content_url", "").startswith("/api/mobile/photos/")
        photo_id = photo["id"]

        # list
        lr = requests.get(f"{BASE_URL}/api/mobile/photos", params={"record_type": "property", "record_id": property_id}, headers=owner_headers, timeout=30)
        assert lr.status_code == 200
        assert any(p["id"] == photo_id for p in lr.json())

        # content
        cr = requests.get(f"{BASE_URL}{photo['content_url']}", headers=owner_headers, timeout=30)
        assert cr.status_code == 200
        assert cr.headers.get("content-type", "").startswith("image/")
        assert len(cr.content) > 0

        # invalid record_type
        files2 = {"file": ("test.png", io.BytesIO(PNG_BYTES), "image/png")}
        data2 = {"record_type": "bogus", "record_id": property_id}
        r2 = requests.post(f"{BASE_URL}/api/mobile/photos", files=files2, data=data2, headers=owner_headers, timeout=30)
        assert r2.status_code == 422, f"Expected 422, got {r2.status_code}: {r2.text}"


# ---- RBAC ----
class TestRBAC:
    def test_unauth_visit_401(self, property_id):
        r = requests.post(f"{BASE_URL}/api/mobile/visits", json={"property_id": property_id, "outcome": "no_answer"}, timeout=30)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_sales_can_create_visit(self, sales_token, property_id):
        h = {"Authorization": f"Bearer {sales_token}", "Idempotency-Key": f"sales-{uuid.uuid4()}"}
        r = requests.post(f"{BASE_URL}/api/mobile/visits", json={"property_id": property_id, "outcome": "no_answer", "notes": "TEST sales visit"}, headers=h, timeout=30)
        assert r.status_code == 201, f"Sales should be a FIELD_ROLE: {r.status_code} {r.text}"


# ---- Office regression ----
class TestOfficeRegression:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=30)
        assert r.status_code == 200

    def test_leads_list(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/leads", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_jobs_list(self, owner_headers):
        r = requests.get(f"{BASE_URL}/api/jobs", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_backup_status_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/backup-status", timeout=30)
        assert r.status_code == 401
