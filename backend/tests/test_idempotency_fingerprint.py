"""P0 backend acceptance: Idempotency-Key fingerprint guard on POST /api/mobile/measurements.

Covers:
 1) Same body replay → 201 first, then 200-or-201 replay returning SAME revision id (replayed=true, no dup).
 2) Different body reuse → 409 with 'reused with a different request body' (data-loss guard).
 3) Regression: normal lifecycle (create 201 → PUT If-Match=updated_at → 200 with new updated_at;
    stale If-Match → 409 with detail.server; invalid facet field → 422).
 4) Regression: Idempotency-Key reused across a DIFFERENT operation type → 409
    'already used for a different operation'.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def property_id(hdr):
    suffix = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE_URL}/api/properties", headers=hdr, json={
        "address_line1": f"TEST_idem_{suffix} 45 Guard Ln",
        "city": "Testville", "state": "TX", "zip_code": "75002",
        "latitude": 32.71, "longitude": -96.81, "property_type": "residential",
    }, timeout=30)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- 1) Same body replay returns same revision ---
class TestIdemSameBodyReplay:
    def test_same_body_replay_returns_same_revision(self, hdr, property_id):
        key = f"idem-same-{uuid.uuid4().hex}"
        headers = dict(hdr); headers["Idempotency-Key"] = key
        payload = {
            "property_id": property_id,
            "structures": [{"name": "A", "structure_type": "main_house", "ref": "s1"}],
        }
        r1 = requests.post(f"{BASE_URL}/api/mobile/measurements",
                           headers=headers, json=payload, timeout=30)
        assert r1.status_code == 201, r1.text
        rev1 = r1.json()
        rev_id = rev1["id"]

        # Repeat EXACT same POST
        r2 = requests.post(f"{BASE_URL}/api/mobile/measurements",
                           headers=headers, json=payload, timeout=30)
        assert r2.status_code in (200, 201), r2.text
        rev2 = r2.json()
        assert rev2["id"] == rev_id, f"Replay must return same revision id; got {rev2['id']} vs {rev_id}"
        # replayed flag should be present and true on replay
        assert rev2.get("replayed") is True, f"Expected replayed=true, got: {rev2}"


# --- 2) The P0 guard: same key + DIFFERENT body → 409 ---
class TestIdemDifferentBodyGuard:
    def test_different_body_same_key_returns_409(self, hdr, property_id):
        key = f"idem-diff-{uuid.uuid4().hex}"
        headers = dict(hdr); headers["Idempotency-Key"] = key
        payload_a = {
            "property_id": property_id,
            "structures": [{"name": "A", "structure_type": "main_house", "ref": "s1"}],
        }
        r1 = requests.post(f"{BASE_URL}/api/mobile/measurements",
                           headers=headers, json=payload_a, timeout=30)
        assert r1.status_code == 201, r1.text
        orig_id = r1.json()["id"]

        # Now DIFFERENT body (different structure name + extra facet)
        payload_b = {
            "property_id": property_id,
            "structures": [{"name": "B_DIFFERENT", "structure_type": "main_house", "ref": "s1"}],
            "facets": [{"structure_ref": "s1", "facet_label": "F1",
                        "pitch_rise": 6, "area_sqft": 200}],
        }
        r2 = requests.post(f"{BASE_URL}/api/mobile/measurements",
                           headers=headers, json=payload_b, timeout=30)
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
        body = r2.json()
        detail = body.get("detail")
        # detail may be a string or object
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert "different request body" in detail_str.lower() or "reused" in detail_str.lower(), \
            f"Expected 'reused with a different request body' detail, got: {detail}"
        # MUST NOT be the original 201 record echoed back
        assert body.get("id") != orig_id, f"Server must not silently accept new body: {body}"


# --- 3) Regression: normal lifecycle ---
class TestLifecycleRegression:
    def test_create_update_stale_and_invalid(self, hdr, property_id):
        # Create
        payload = {"property_id": property_id,
                   "structures": [{"name": "L", "structure_type": "main_house", "ref": "s1"}]}
        r = requests.post(f"{BASE_URL}/api/mobile/measurements",
                          headers=hdr, json=payload, timeout=30)
        assert r.status_code == 201, r.text
        rev = r.json()
        rev_id = rev["id"]
        updated_at = rev["updated_at"]

        # Update with If-Match=updated_at → 200 with new updated_at
        upd_payload = {"property_id": property_id,
                       "structures": [{"name": "L2", "structure_type": "main_house"}]}
        h = dict(hdr); h["If-Match"] = updated_at
        r_upd = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                             headers=h, json=upd_payload, timeout=30)
        assert r_upd.status_code == 200, r_upd.text
        new_updated_at = r_upd.json()["updated_at"]
        assert new_updated_at != updated_at

        # Stale If-Match → 409 with detail.server
        h2 = dict(hdr); h2["If-Match"] = "2020-01-01T00:00:00+00:00"
        r_stale = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                               headers=h2, json=upd_payload, timeout=30)
        assert r_stale.status_code == 409, r_stale.text
        detail = r_stale.json().get("detail")
        assert isinstance(detail, dict), f"detail must be dict on conflict: {detail}"
        server = detail.get("server")
        assert isinstance(server, dict), f"detail.server required: {detail}"
        assert server.get("id") == rev_id
        assert server.get("updated_at") is not None

        # Invalid field → 422
        bad_payload = {
            "property_id": property_id,
            "structures": [{"name": "L2", "structure_type": "main_house", "ref": "s1"}],
            "facets": [{"structure_ref": "s1", "facet_label": "F1",
                        "pitch_rise": "not-a-number", "area_sqft": 10}],
        }
        h3 = dict(hdr); h3["If-Match"] = new_updated_at
        r_bad = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                             headers=h3, json=bad_payload, timeout=30)
        assert r_bad.status_code in (400, 422), f"Expected 4xx, got {r_bad.status_code}: {r_bad.text}"


# --- 4) Regression: key reused across a DIFFERENT operation type ---
class TestIdemCrossOperation:
    def test_key_reused_across_different_operation(self, hdr, property_id):
        key = f"idem-xop-{uuid.uuid4().hex}"
        headers = dict(hdr); headers["Idempotency-Key"] = key

        # First: use as a mobile_measurement create
        r1 = requests.post(f"{BASE_URL}/api/mobile/measurements",
                           headers=headers,
                           json={"property_id": property_id,
                                 "structures": [{"name": "X", "structure_type": "main_house"}]},
                           timeout=30)
        assert r1.status_code == 201, r1.text

        # Now reuse SAME key for a lead create (different entity_type) → 409
        r2 = requests.post(f"{BASE_URL}/api/mobile/leads",
                           headers=headers,
                           json={"name": f"TEST_xop_{uuid.uuid4().hex[:6]}",
                                 "property_id": property_id},
                           timeout=30)
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail")
        detail_str = detail if isinstance(detail, str) else str(detail)
        assert "different operation" in detail_str.lower(), \
            f"Expected 'different operation' detail, got: {detail}"
