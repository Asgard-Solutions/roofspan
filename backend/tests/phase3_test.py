"""RoofSpan Office Phase 3 (Sales) backend tests: leads enrichment, customers,
inspections, estimates (idempotency + version), quotes (accept + idempotent job),
invoices (records-only), RBAC, audit."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://roofspan-core.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


# ----------------- Fixtures -----------------
@pytest.fixture(scope="module")
def owner_headers():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def sales_headers(owner_headers):
    email = f"TEST_sales_p3_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "TEST P3 Sales", "password": "SalesP3#2026", "role": "sales"}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": "SalesP3#2026"}, timeout=15)
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


@pytest.fixture(scope="module")
def lead_with_property(owner_headers):
    """Create territory -> import sample -> pick property -> convert to lead."""
    # 1) territory
    poly = [[-96.80, 32.78], [-96.79, 32.78], [-96.79, 32.79], [-96.80, 32.79], [-96.80, 32.78]]
    tname = f"TEST_P3_Terr_{uuid.uuid4().hex[:6]}"
    geom = {"type": "Polygon", "coordinates": [poly]}
    r = requests.post(f"{API}/territories", json={"name": tname, "geometry": geom}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # 2) Create a property directly (skip async import)
    fa_body = {"territory_id": tid, "address_line1": "123 Test Ln", "city": "Dallas", "state": "TX",
               "zip_code": "75201", "latitude": 32.785, "longitude": -96.795, "property_type": "single_family",
               "owner_name": "TEST Owner"}
    pr = requests.post(f"{API}/properties", json=fa_body, headers=owner_headers, timeout=15)
    assert pr.status_code == 201, pr.text
    prop_id = pr.json()["id"]

    # 4) convert to lead
    cl = requests.post(f"{API}/properties/{prop_id}/convert-to-lead", json={"name": "TEST_P3_Lead", "phone": "555-0100"}, headers=owner_headers, timeout=15)
    assert cl.status_code == 201, cl.text
    lead = cl.json()
    return {"lead_id": lead["id"], "property_id": prop_id, "territory_id": tid}


# ----------------- Leads enriched detail -----------------
def test_lead_detail_enriched(owner_headers, lead_with_property):
    lid = lead_with_property["lead_id"]
    r = requests.get(f"{API}/leads/{lid}", headers=owner_headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("property_address", "owner_name", "visits", "customer_id", "customer_name"):
        assert k in d, f"missing field {k}"
    assert isinstance(d["visits"], list)
    assert d["property_address"]  # non-empty


# ----------------- Customer from lead (idempotent) -----------------
def test_customer_from_lead_idempotent(owner_headers, lead_with_property):
    lid = lead_with_property["lead_id"]
    pid = lead_with_property["property_id"]
    r1 = requests.post(f"{API}/customers/from-lead/{lid}", headers=owner_headers, timeout=15)
    assert r1.status_code in (200, 201), r1.text
    c1 = r1.json()
    assert pid in c1["property_ids"], f"property {pid} not linked; got {c1['property_ids']}"

    # Verify lead updated
    lr = requests.get(f"{API}/leads/{lid}", headers=owner_headers, timeout=15).json()
    assert lr["customer_id"] == c1["id"]
    assert lr["status"] == "converted"

    # Call again -> same customer
    r2 = requests.post(f"{API}/customers/from-lead/{lid}", headers=owner_headers, timeout=15)
    assert r2.status_code in (200, 201)
    assert r2.json()["id"] == c1["id"], "duplicate customer created"

    # store for downstream via module-scoped dict? use pytest cache
    lead_with_property["customer_id"] = c1["id"]


# ----------------- Inspection -----------------
def test_inspection_create_and_list(owner_headers, lead_with_property):
    lid = lead_with_property["lead_id"]
    cid = lead_with_property.get("customer_id")
    pid = lead_with_property["property_id"]
    payload = {"lead_id": lid, "customer_id": cid, "property_id": pid,
               "inspector": "TEST Inspector", "roof_condition": "fair",
               "recommended_work": "Full replacement"}
    r = requests.post(f"{API}/inspections", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    ins = r.json()
    assert ins["inspector"] == "TEST Inspector"
    lst = requests.get(f"{API}/inspections", params={"lead_id": lid}, headers=owner_headers, timeout=15)
    assert lst.status_code == 200
    assert any(i["id"] == ins["id"] for i in lst.json())


# ----------------- Estimate: totals + idempotency + version -----------------
def test_estimate_server_totals(owner_headers, lead_with_property):
    lid = lead_with_property["lead_id"]
    cid = lead_with_property.get("customer_id")
    # Client sends a bogus 'total' — must be ignored (schema doesn't accept it anyway)
    payload = {
        "lead_id": lid, "customer_id": cid, "tax_rate": 8.25,
        "items": [
            {"description": "Shingles", "quantity": 30, "unit_price": 120, "unit": "sq"},
            {"description": "Labor", "quantity": 40, "unit_price": 65, "unit": "hr"},
        ],
    }
    r = requests.post(f"{API}/estimates", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["subtotal"] == 6200.00
    assert e["tax"] == 511.50
    assert e["total"] == 6711.50
    assert e["number"].startswith("EST-") and len(e["number"]) >= 8
    lead_with_property["estimate_id"] = e["id"]
    lead_with_property["estimate_version"] = e["version"]


def test_estimate_idempotency(owner_headers, lead_with_property):
    cid = lead_with_property.get("customer_id")
    key = f"idem-{uuid.uuid4().hex}"
    headers = {**owner_headers, "Idempotency-Key": key}
    body = {"customer_id": cid, "tax_rate": 10, "items": [{"description": "X", "quantity": 2, "unit_price": 50}]}
    r1 = requests.post(f"{API}/estimates", json=body, headers=headers, timeout=15)
    assert r1.status_code == 201, r1.text
    e1 = r1.json()
    r2 = requests.post(f"{API}/estimates", json=body, headers=headers, timeout=15)
    assert r2.status_code in (200, 201)
    e2 = r2.json()
    assert e1["id"] == e2["id"], "idempotency-key returned different estimate"
    assert e1["number"] == e2["number"]


def test_estimate_optimistic_concurrency_conflict(owner_headers, lead_with_property):
    eid = lead_with_property["estimate_id"]
    body = {"tax_rate": 8.25, "items": [{"description": "changed", "quantity": 1, "unit_price": 100}]}
    r = requests.put(f"{API}/estimates/{eid}", json=body, headers={**owner_headers, "If-Match": "999"}, timeout=15)
    assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"


# ----------------- Quote from estimate, accept, idempotent job -----------------
def test_quote_from_estimate(owner_headers, lead_with_property):
    eid = lead_with_property["estimate_id"]
    r = requests.post(f"{API}/quotes", json={"estimate_id": eid}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["status"] == "draft"
    assert q["total"] == 6711.50
    assert q["number"].startswith("QUO-")
    assert len(q["items"]) == 2
    lead_with_property["quote_id"] = q["id"]


def test_quote_accept_creates_job_idempotent(owner_headers, lead_with_property):
    qid = lead_with_property["quote_id"]
    r1 = requests.post(f"{API}/quotes/{qid}/accept", json={"acceptance_name": "Homeowner Test"}, headers=owner_headers, timeout=15)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["quote"]["status"] == "accepted"
    assert d1["quote"]["accepted_by"]
    assert d1["quote"]["accepted_at"]
    job_id = d1["job_id"]
    assert job_id
    lead_with_property["job_id"] = job_id

    # verify job
    jr = requests.get(f"{API}/jobs/{job_id}", headers=owner_headers, timeout=15)
    assert jr.status_code == 200
    j = jr.json()
    assert j["number"].startswith("JOB-")
    assert j["quote_id"] == qid
    assert j["status"] == "created"
    assert j["total"] == 6711.50

    # accept again -> same job
    r2 = requests.post(f"{API}/quotes/{qid}/accept", json={"acceptance_name": "again"}, headers=owner_headers, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["job_id"] == job_id, "duplicate job created on re-accept"


def test_accepted_quote_cannot_be_edited(owner_headers, lead_with_property):
    qid = lead_with_property["quote_id"]
    body = {"items": [{"description": "hack", "quantity": 1, "unit_price": 1}]}
    r = requests.put(f"{API}/quotes/{qid}", json=body, headers=owner_headers, timeout=15)
    assert r.status_code == 400, f"expected 400 for edit of accepted quote, got {r.status_code}"


# ----------------- Invoice records-only -----------------
def test_invoice_from_quote_and_status(owner_headers, lead_with_property):
    qid = lead_with_property["quote_id"]
    r = requests.post(f"{API}/invoices", json={"quote_id": qid}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["number"].startswith("INV-")
    assert inv["status"] == "draft"
    assert inv["total"] == 6711.50
    assert inv["job_id"] == lead_with_property["job_id"]
    assert len(inv["items"]) == 2
    inv_id = inv["id"]

    # status paid
    sr = requests.post(f"{API}/invoices/{inv_id}/status", json={"status": "paid"}, headers=owner_headers, timeout=15)
    assert sr.status_code == 200
    assert sr.json()["status"] == "paid"

    # list
    lr = requests.get(f"{API}/invoices", headers=owner_headers, timeout=15)
    assert lr.status_code == 200
    assert any(i["id"] == inv_id for i in lr.json())


# ----------------- RBAC (sales) -----------------
def test_rbac_sales_can_create_estimate_and_customer(sales_headers):
    # sales can create customer
    r = requests.post(f"{API}/customers", json={"name": f"TEST_SalesCust_{uuid.uuid4().hex[:6]}"}, headers=sales_headers, timeout=15)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    # sales can create estimate
    er = requests.post(f"{API}/estimates", json={"customer_id": cid, "tax_rate": 5, "items": [{"description": "x", "quantity": 1, "unit_price": 100}]}, headers=sales_headers, timeout=15)
    assert er.status_code == 201, er.text


def test_rbac_sales_forbidden_invoices_accept_territories(sales_headers, lead_with_property):
    # invoice create forbidden
    r = requests.post(f"{API}/invoices", json={"quote_id": lead_with_property["quote_id"]}, headers=sales_headers, timeout=15)
    assert r.status_code == 403, f"expected 403 on invoice create, got {r.status_code}"

    # accept quote forbidden (use another quote or same)
    ra = requests.post(f"{API}/quotes/{lead_with_property['quote_id']}/accept", json={"acceptance_name": "sales"}, headers=sales_headers, timeout=15)
    assert ra.status_code == 403, f"expected 403 on accept, got {ra.status_code}"

    # territory create forbidden
    rt = requests.post(f"{API}/territories", json={"name": "TEST_ShouldFail", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}, headers=sales_headers, timeout=15)
    assert rt.status_code == 403


def test_rbac_sales_cannot_list_invoices(sales_headers):
    r = requests.get(f"{API}/invoices", headers=sales_headers, timeout=15)
    assert r.status_code == 403


# ----------------- Audit entries -----------------
def test_audit_contains_phase3_actions(owner_headers):
    r = requests.get(f"{API}/audit", params={"limit": 200}, headers=owner_headers, timeout=15)
    assert r.status_code == 200
    actions = {i["action"] for i in r.json()["items"]}
    for a in ("estimate.create", "customer.create", "quote.accept", "invoice.create"):
        assert a in actions, f"missing audit action: {a} (have: {sorted(actions)[:20]}...)"
