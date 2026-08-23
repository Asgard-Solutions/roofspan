"""
Test CRUD + accepted-guard behavior for estimates and quotes.
- Non-accepted estimate: full CRUD (create, read, update, delete)
- Draft quote: DELETE works (200)
- Accepted quote: DELETE => 409; PUT => 400
- Estimate with accepted quote: DELETE => 409; PUT => 409
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    r = sess.post(f"{BASE_URL}/api/auth/login",
                  json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
                  allow_redirects=True)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"No token in login response: {r.json()}"
    sess.headers.update({"Authorization": f"Bearer {token}"})
    return sess


@pytest.fixture(scope="module")
def ctx(s):
    """Create property → lead → customer, return ids."""
    tag = uuid.uuid4().hex[:8]
    # Create property
    r = s.post(f"{BASE_URL}/api/properties",
               json={
                   "address_line1": f"{tag} Test St",
                   "city": "Testville",
                   "state": "TX",
                   "zip_code": "75001",
                   "owner_name": f"TEST_Owner_{tag}",
               }, allow_redirects=True)
    assert r.status_code in (200, 201), f"property create: {r.status_code} {r.text}"
    prop_id = r.json()["id"]

    # Convert to lead
    r = s.post(f"{BASE_URL}/api/properties/{prop_id}/convert-to-lead",
               json={"name": f"TEST_Lead_{tag}", "phone": "555-0000",
                     "email": f"test_{tag}@example.com"},
               allow_redirects=True)
    assert r.status_code in (200, 201), f"convert-to-lead: {r.status_code} {r.text}"
    lead_id = r.json()["id"]

    # Customer from lead
    r = s.post(f"{BASE_URL}/api/customers/from-lead/{lead_id}", json={},
               allow_redirects=True)
    assert r.status_code in (200, 201), f"customer create: {r.status_code} {r.text}"
    cust_id = r.json()["id"]

    return {"property_id": prop_id, "lead_id": lead_id, "customer_id": cust_id, "tag": tag}


def _estimate_payload(ctx):
    return {
        "lead_id": ctx["lead_id"],
        "customer_id": ctx["customer_id"],
        "property_id": ctx["property_id"],
        "tax_rate": 8.25,
        "notes": "TEST",
        "items": [
            {"description": "Shingle install", "quantity": 10, "unit": "sq",
             "unit_price": 350.0, "line_kind": "custom"},
        ],
    }


def _create_estimate(s, ctx):
    r = s.post(f"{BASE_URL}/api/estimates", json=_estimate_payload(ctx),
               allow_redirects=True)
    assert r.status_code in (200, 201), f"est create: {r.status_code} {r.text}"
    return r.json()


def _create_quote(s, estimate_id):
    r = s.post(f"{BASE_URL}/api/quotes", json={"estimate_id": estimate_id},
               allow_redirects=True)
    assert r.status_code in (200, 201), f"quote create: {r.status_code} {r.text}"
    return r.json()


# ---------- Tests ----------
class TestEstimateCRUD:
    def test_create_read_update_delete_estimate(self, s, ctx):
        est = _create_estimate(s, ctx)
        est_id = est["id"]

        # READ
        r = s.get(f"{BASE_URL}/api/estimates/{est_id}")
        assert r.status_code == 200
        assert r.json()["id"] == est_id

        # UPDATE (no accepted quote) => 200
        upd = _estimate_payload(ctx)
        upd["notes"] = "TEST_UPDATED"
        r = s.put(f"{BASE_URL}/api/estimates/{est_id}", json=upd)
        assert r.status_code == 200, f"PUT est: {r.status_code} {r.text}"
        assert r.json()["notes"] == "TEST_UPDATED"

        # DELETE => 200
        r = s.delete(f"{BASE_URL}/api/estimates/{est_id}")
        assert r.status_code == 200, f"DELETE est: {r.status_code} {r.text}"
        assert r.json().get("deleted") is True

        # Verify gone
        r = s.get(f"{BASE_URL}/api/estimates/{est_id}")
        assert r.status_code == 404


class TestQuoteDeleteDraft:
    def test_delete_draft_quote(self, s, ctx):
        est = _create_estimate(s, ctx)
        q = _create_quote(s, est["id"])
        q_id = q["id"]
        assert q.get("status") != "accepted"

        # DELETE draft quote => 200
        r = s.delete(f"{BASE_URL}/api/quotes/{q_id}")
        assert r.status_code == 200, f"DELETE quote draft: {r.status_code} {r.text}"

        # Verify gone
        r = s.get(f"{BASE_URL}/api/quotes/{q_id}")
        assert r.status_code == 404

        # Cleanup estimate too
        s.delete(f"{BASE_URL}/api/estimates/{est['id']}")


class TestAcceptedLocks:
    """After accepting a quote: quote DELETE=>409, quote PUT=>400,
       estimate DELETE=>409, estimate PUT=>409."""

    @pytest.fixture(scope="class")
    def accepted(self, s, ctx):
        est = _create_estimate(s, ctx)
        q = _create_quote(s, est["id"])
        r = s.post(f"{BASE_URL}/api/quotes/{q['id']}/accept",
                   json={"acceptance_name": "Test Accept"})
        assert r.status_code == 200, f"accept: {r.status_code} {r.text}"
        body = r.json()
        # QuoteAcceptResult: {quote: {...}, job_id: ...}
        assert body["quote"]["status"] == "accepted"
        return {"estimate_id": est["id"], "quote_id": q["id"]}

    def test_delete_accepted_quote_returns_409(self, s, accepted):
        r = s.delete(f"{BASE_URL}/api/quotes/{accepted['quote_id']}")
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"

    def test_update_accepted_quote_returns_400(self, s, accepted):
        r = s.put(f"{BASE_URL}/api/quotes/{accepted['quote_id']}",
                  json={"terms": "changed"})
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_delete_locked_estimate_returns_409(self, s, accepted, ctx):
        r = s.delete(f"{BASE_URL}/api/estimates/{accepted['estimate_id']}")
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"

    def test_update_locked_estimate_returns_409(self, s, accepted, ctx):
        r = s.put(f"{BASE_URL}/api/estimates/{accepted['estimate_id']}",
                  json=_estimate_payload(ctx))
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
