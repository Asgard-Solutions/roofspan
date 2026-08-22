"""ABC Supply — Delivery Address Review & Editor (iter_28) API tests.

Covers the specific regression fix and enhancement:
  1. abc-submit-review returns a 'delivery' object (defaulted from job/property or blank).
  2. abc-submit with a FULL delivery override -> confirmed; abc_order_submissions.delivery
     persists the EXACT edited values; PO.abc_ship_to_number is unchanged (still 1163698);
     GET /api/purchase-orders/{po_id} returns abc_delivery snapshot.
  3. Editing delivery MUST NOT modify the linked Job's Property/Customer records.
  4. OPTIONAL override (empty delivery) -> confirmed (KEY regression fix; must NOT be
     validation_failed).
  5. PARTIAL override (only line1) -> validation_failed with errors naming missing
     city/state/ZIP.

Run serially (single-file) — the ABC mock uses in-memory state.
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
CLIENT_ID = "mock-client-id-123456"
CLIENT_SECRET = "mock-secret-abcdef"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_headers():
    return {"Authorization": f"Bearer {_login(*OWNER)}"}


@pytest.fixture(scope="module", autouse=True)
def _ensure_connected(owner_headers):
    requests.put(f"{BASE_URL}/api/integrations/abc/config", headers=owner_headers,
                 json={"environment": "sandbox", "client_id": CLIENT_ID}, timeout=30)
    requests.put(f"{BASE_URL}/api/integrations/abc/config/secret", headers=owner_headers,
                 json={"client_secret": CLIENT_SECRET}, timeout=30)
    st = requests.get(f"{BASE_URL}/api/integrations/abc/status", headers=owner_headers, timeout=30).json()
    if st.get("status") != "connected":
        requests.post(f"{BASE_URL}/api/integrations/abc/disconnect", headers=owner_headers, timeout=30)
        r = requests.post(f"{BASE_URL}/api/integrations/abc/connect", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        s = requests.Session()
        authorize_url = r.json()["authorize_url"]
        r1 = s.get(authorize_url, allow_redirects=False, timeout=30)
        assert r1.status_code == 302
        cb = r1.headers["location"]
        if cb.startswith("/"):
            cb = BASE_URL + cb
        r2 = s.get(cb, allow_redirects=False, timeout=30)
        assert r2.status_code == 302
    requests.put(f"{BASE_URL}/api/integrations/abc/defaults", headers=owner_headers,
                 json={"default_ship_to_number": "1163698", "default_branch_number": "18"}, timeout=30)


def _abc_line(item="MOCK-SHINGLE-ARCH-WW", qty=10, cost=135.36, uom="SQ"):
    return {
        "description": "Shingle", "quantity": qty, "unit": uom, "unit_cost": cost,
        "integration_provider": "abc_supply", "abc_item_number": item,
        "abc_branch_number": "18", "abc_ship_to_number": "1163698", "abc_uom": uom,
        "abc_price": cost, "abc_price_status": "priced", "pricing_source": "abc",
    }


def _create_abc_po(headers, notes="TEST_DELIVERY", job_id=None):
    payload = {
        "supplier_name": "ABC Supply", "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698", "abc_branch_number": "18",
        "notes": notes, "items": [_abc_line()],
    }
    if job_id:
        payload["job_id"] = job_id
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=headers, json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    return r.json()


# ---------------- Tests ----------------

class TestSubmitReviewReturnsDelivery:
    def test_review_returns_delivery_field(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_review")
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                          headers=owner_headers, json={}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "delivery" in data, data
        d = data["delivery"]
        # Structure keys present (even if empty since no linked job)
        for k in ("name", "line1", "city", "state", "postal", "country",
                  "contact_name", "contact_phone", "instructions"):
            assert k in d, f"missing key {k} in delivery: {d}"
        assert d["country"] == "USA"


class TestSubmitWithFullDeliveryOverride:
    def test_full_override_confirmed_and_persisted(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_full")
        override = {
            "name": "Edited Site", "line1": "500 Testing Way", "line2": "Suite 9",
            "city": "Austin", "state": "TX", "postal": "78701",
            "contact_name": "Jane Foreman", "contact_phone": "512-555-0199",
            "instructions": "Leave at back gate",
        }
        key = f"sub-fullov-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key, "delivery": override}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "confirmed", body
        assert body["confirmation_number"].startswith("MOCK-CONF-")

        # GET PO -> abc_delivery snapshot must equal override values
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}",
                              headers=owner_headers, timeout=30).json()
        assert "abc_delivery" in po_get and po_get["abc_delivery"] is not None, po_get
        snap = po_get["abc_delivery"]
        for k, v in override.items():
            assert snap.get(k) == v, f"delivery.{k} expected {v!r} got {snap.get(k)!r}"

        # abc_ship_to_number unchanged
        assert po_get.get("abc_ship_to_number") == "1163698"


class TestSubmitWithNoOverrideOptional:
    """KEY regression: empty delivery override MUST be accepted (falls back to ABC Ship-To)."""

    def test_no_override_confirms(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_noov")
        key = f"sub-noov-{uuid.uuid4().hex}"
        # Case A: delivery omitted entirely
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers, json={"submission_key": key}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "confirmed", body

    def test_empty_dict_override_confirms(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_emptyov")
        key = f"sub-empty-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key, "delivery": {}}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "confirmed"

    def test_blank_strings_override_confirms(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_blank")
        key = f"sub-blank-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key,
                                "delivery": {"line1": "", "city": "", "state": "", "postal": ""}},
                          timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["status"] == "confirmed", r.json()


class TestSubmitWithPartialOverrideRejected:
    def test_partial_only_line1_rejected(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_partial1")
        key = f"sub-part1-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key,
                                "delivery": {"line1": "123 Nowhere St"}}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "validation_failed", body
        errs = " ".join(body.get("errors", [])).lower()
        assert "city" in errs, errs
        assert "state" in errs, errs
        assert "zip" in errs or "postal" in errs, errs

    def test_partial_missing_state_rejected(self, owner_headers):
        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_partial2")
        key = f"sub-part2-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key,
                                "delivery": {"line1": "1 Main", "city": "Dallas", "postal": "75001"}},
                          timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "validation_failed", body
        errs = " ".join(body.get("errors", [])).lower()
        assert "state" in errs, errs


class TestDeliveryDoesNotMutateJobRecords:
    """Editing delivery must not modify Property/Customer records of a linked Job."""

    def _create_customer_property_job(self, headers):
        # Customer
        cust_body = {"name": "TEST_DELIVERY_Cust", "phone": "555-000-1111",
                     "email": f"cust_{uuid.uuid4().hex[:6]}@t.local"}
        rc = requests.post(f"{BASE_URL}/api/customers", headers=headers, json=cust_body, timeout=30)
        if rc.status_code not in (200, 201):
            pytest.skip(f"cannot create customer: {rc.status_code} {rc.text[:200]}")
        cust = rc.json()
        # Property
        prop_body = {"customer_id": cust["id"], "address_line1": "111 Orig St",
                     "city": "OrigCity", "state": "CA", "zip_code": "90001"}
        rp = requests.post(f"{BASE_URL}/api/properties", headers=headers, json=prop_body, timeout=30)
        if rp.status_code not in (200, 201):
            pytest.skip(f"cannot create property: {rp.status_code} {rp.text[:200]}")
        prop = rp.json()
        # Job
        job_body = {"customer_id": cust["id"], "property_id": prop["id"],
                    "name": "TEST_DELIVERY_Job", "type": "roof_replacement"}
        rj = requests.post(f"{BASE_URL}/api/jobs", headers=headers, json=job_body, timeout=30)
        if rj.status_code not in (200, 201):
            pytest.skip(f"cannot create job: {rj.status_code} {rj.text[:200]}")
        return cust, prop, rj.json()

    def test_edit_delivery_does_not_change_property_or_customer(self, owner_headers):
        cust, prop, job = self._create_customer_property_job(owner_headers)

        # Snapshot Property/Customer BEFORE
        prop_before = requests.get(f"{BASE_URL}/api/properties/{prop['id']}",
                                   headers=owner_headers, timeout=30).json()
        cust_before = requests.get(f"{BASE_URL}/api/customers/{cust['id']}",
                                   headers=owner_headers, timeout=30).json()

        po = _create_abc_po(owner_headers, notes="TEST_DELIVERY_jobln", job_id=job["id"])
        # Review returns defaulted delivery from property/customer
        rv = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit-review",
                           headers=owner_headers, json={}, timeout=30).json()
        d = rv["delivery"]
        assert d["line1"] == "111 Orig St"
        assert d["city"] == "OrigCity"
        assert d["state"] == "CA"
        assert d["postal"] == "90001"

        # Submit with EDITED delivery
        override = {"name": "New Site Name", "line1": "999 Edited Ave", "city": "NewTown",
                    "state": "NY", "postal": "10001", "contact_name": "Ed", "contact_phone": "111"}
        key = f"sub-jobov-{uuid.uuid4().hex}"
        r = requests.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/abc-submit",
                          headers=owner_headers,
                          json={"submission_key": key, "delivery": override}, timeout=60)
        assert r.status_code == 200 and r.json()["status"] == "confirmed", r.text[:300]

        # Verify Property/Customer AFTER unchanged
        prop_after = requests.get(f"{BASE_URL}/api/properties/{prop['id']}",
                                  headers=owner_headers, timeout=30).json()
        cust_after = requests.get(f"{BASE_URL}/api/customers/{cust['id']}",
                                  headers=owner_headers, timeout=30).json()
        for k in ("address_line1", "city", "state", "zip_code"):
            assert prop_after.get(k) == prop_before.get(k), \
                f"Property.{k} changed! before={prop_before.get(k)!r} after={prop_after.get(k)!r}"
        assert cust_after.get("name") == cust_before.get("name")
        assert cust_after.get("phone") == cust_before.get("phone")

        # PO snapshot has edited delivery
        po_get = requests.get(f"{BASE_URL}/api/purchase-orders/{po['id']}",
                              headers=owner_headers, timeout=30).json()
        for k, v in override.items():
            assert po_get["abc_delivery"].get(k) == v
        assert po_get["abc_ship_to_number"] == "1163698"
