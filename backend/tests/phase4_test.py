"""RoofSpan Phase 4 (Operations) backend tests: materials catalog, inventory,
job scheduling (audit datetime serialization), job materials, purchase orders,
partial/full receiving, idempotent receiving, RBAC."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://unified-mono-deploy.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


# ------------------ Fixtures ------------------
@pytest.fixture(scope="module")
def owner_headers():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def sales_headers(owner_headers):
    email = f"TEST_sales_p4_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "TEST P4 Sales", "password": "SalesP4#2026", "role": "sales"}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    lr = requests.post(f"{API}/auth/login", json={"email": email, "password": "SalesP4#2026"}, timeout=15)
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


@pytest.fixture(scope="module")
def state():
    """Shared bag between tests."""
    return {}


@pytest.fixture(scope="module")
def job_id(owner_headers, state):
    """Build sales chain: territory -> property -> lead -> customer -> estimate -> quote -> accept -> job."""
    poly = [[-96.80, 32.78], [-96.79, 32.78], [-96.79, 32.79], [-96.80, 32.79], [-96.80, 32.78]]
    tname = f"TEST_P4_Terr_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/territories", json={"name": tname, "geometry": {"type": "Polygon", "coordinates": [poly]}}, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    pr = requests.post(f"{API}/properties", json={
        "territory_id": tid, "address_line1": "77 Phase4 Way", "city": "Dallas", "state": "TX",
        "zip_code": "75202", "latitude": 32.786, "longitude": -96.796, "property_type": "single_family",
        "owner_name": "TEST P4 Owner"}, headers=owner_headers, timeout=15)
    assert pr.status_code == 201, pr.text
    prop_id = pr.json()["id"]

    cl = requests.post(f"{API}/properties/{prop_id}/convert-to-lead", json={"name": "TEST_P4_Lead", "phone": "555-0400"}, headers=owner_headers, timeout=15)
    assert cl.status_code == 201, cl.text
    lid = cl.json()["id"]

    cr = requests.post(f"{API}/customers/from-lead/{lid}", headers=owner_headers, timeout=15)
    assert cr.status_code in (200, 201), cr.text
    cid = cr.json()["id"]

    er = requests.post(f"{API}/estimates", json={"lead_id": lid, "customer_id": cid, "tax_rate": 8.25,
                                                 "items": [{"description": "Shingles", "quantity": 20, "unit_price": 100, "unit": "sq"}]},
                       headers=owner_headers, timeout=15)
    assert er.status_code == 201, er.text
    eid = er.json()["id"]

    qr = requests.post(f"{API}/quotes", json={"estimate_id": eid}, headers=owner_headers, timeout=15)
    assert qr.status_code == 201, qr.text
    qid = qr.json()["id"]

    ar = requests.post(f"{API}/quotes/{qid}/accept", json={"acceptance_name": "Homeowner P4"}, headers=owner_headers, timeout=15)
    assert ar.status_code == 200, ar.text
    jid = ar.json()["job_id"]
    state["job_id"] = jid
    return jid


# ------------------ Materials ------------------
def test_material_create_and_low_stock_flag(owner_headers, state):
    name = f"TEST_Mat_Shingle_{uuid.uuid4().hex[:6]}"
    payload = {"name": name, "unit": "bundle", "reorder_threshold": 10, "quantity_on_hand": 5}
    r = requests.post(f"{API}/materials", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["name"] == name
    assert m["quantity_on_hand"] == 5
    assert m["reorder_threshold"] == 10
    assert m["low_stock"] is True, f"expected low_stock True; got {m}"
    state["mat_low_id"] = m["id"]

    # Second material - not low
    name2 = f"TEST_Mat_Nails_{uuid.uuid4().hex[:6]}"
    r2 = requests.post(f"{API}/materials", json={"name": name2, "unit": "box", "reorder_threshold": 2, "quantity_on_hand": 20}, headers=owner_headers, timeout=15)
    assert r2.status_code == 201
    m2 = r2.json()
    assert m2["low_stock"] is False
    state["mat_ok_id"] = m2["id"]


def test_material_list_and_filter(owner_headers, state):
    r = requests.get(f"{API}/materials", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()}
    assert state["mat_low_id"] in ids
    assert state["mat_ok_id"] in ids

    r_low = requests.get(f"{API}/materials", params={"low_stock": "true"}, headers=owner_headers, timeout=15)
    assert r_low.status_code == 200
    low_ids = {m["id"] for m in r_low.json()}
    assert state["mat_low_id"] in low_ids
    assert state["mat_ok_id"] not in low_ids


def test_material_patch(owner_headers, state):
    mid = state["mat_ok_id"]
    r = requests.patch(f"{API}/materials/{mid}", json={"reorder_threshold": 25}, headers=owner_headers, timeout=15)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["reorder_threshold"] == 25
    # 20 <= 25 -> low_stock now True
    assert m["low_stock"] is True
    # Revert
    requests.patch(f"{API}/materials/{mid}", json={"reorder_threshold": 2}, headers=owner_headers, timeout=15)


def test_material_adjust_positive_and_flag_flip(owner_headers, state):
    mid = state["mat_low_id"]  # currently 5 on hand, threshold 10
    r = requests.post(f"{API}/materials/{mid}/adjust", json={"delta": 20, "reason": "adjustment"}, headers=owner_headers, timeout=15)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["quantity_on_hand"] == 25
    assert m["low_stock"] is False


def test_material_adjust_negative_guard(owner_headers, state):
    mid = state["mat_ok_id"]  # 20 on hand
    r = requests.post(f"{API}/materials/{mid}/adjust", json={"delta": -9999, "reason": "test"}, headers=owner_headers, timeout=15)
    assert r.status_code == 400


# ------------------ Job Scheduling (datetime serialization bug regression) ------------------
def test_job_schedule_no_datetime_serialization_error(owner_headers, job_id, state):
    payload = {
        "status": "scheduled",
        "scheduled_start": "2026-09-01T08:00:00Z",
        "scheduled_end": "2026-09-01T17:00:00Z",
        "schedule_notes": "First tear-off crew",
        "assigned_to": "Crew A",
    }
    r = requests.patch(f"{API}/jobs/{job_id}", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 200, f"schedule failed: {r.status_code} {r.text}"
    j = r.json()
    assert j["status"] == "scheduled"
    assert j["scheduled_start"] is not None
    assert j["assigned_to"] == "Crew A"

    # Verify audit row present with action='job.update' and NO error surfaced
    ar = requests.get(f"{API}/audit", params={"limit": 50, "action": "job.update"}, headers=owner_headers, timeout=15)
    assert ar.status_code == 200, ar.text
    items = ar.json().get("items", [])
    matches = [i for i in items if i.get("entity_id") == job_id and i.get("action") == "job.update"]
    assert matches, f"expected job.update audit row for {job_id}; got actions={[i.get('action') for i in items][:10]}"
    # audit detail should be a dict/JSON – check no error markers
    detail = matches[0].get("detail")
    if detail:
        assert isinstance(detail, (dict, str))
        # ensure scheduled_start present as ISO string if included
        if isinstance(detail, dict) and "scheduled_start" in detail:
            assert isinstance(detail["scheduled_start"], str)


def test_job_schedule_repeat_no_error(owner_headers, job_id):
    """Repeat multiple PATCHes to ensure clean audit writes with datetimes."""
    for i in range(3):
        payload = {"schedule_notes": f"note-{i}", "scheduled_start": f"2026-09-0{i+2}T08:00:00Z"}
        r = requests.patch(f"{API}/jobs/{job_id}", json=payload, headers=owner_headers, timeout=15)
        assert r.status_code == 200, f"iter {i}: {r.text}"


# ------------------ Job Materials ------------------
def test_add_job_material_and_list(owner_headers, job_id, state):
    r = requests.post(f"{API}/jobs/{job_id}/materials",
                      json={"material_id": state["mat_low_id"], "planned_quantity": 30, "notes": "for roof"},
                      headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    jm = r.json()
    assert jm["planned_quantity"] == 30
    assert "quantity_on_hand" in jm
    assert "low_stock" in jm

    lr = requests.get(f"{API}/jobs/{job_id}/materials", headers=owner_headers, timeout=15)
    assert lr.status_code == 200
    assert any(x["id"] == jm["id"] for x in lr.json())


def test_job_detail_includes_materials_and_pos(owner_headers, job_id):
    r = requests.get(f"{API}/jobs/{job_id}", headers=owner_headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "materials" in d and isinstance(d["materials"], list)
    assert len(d["materials"]) >= 1
    assert "purchase_orders" in d and isinstance(d["purchase_orders"], list)


# ------------------ Purchase Orders ------------------
def test_create_purchase_order(owner_headers, job_id, state):
    mid = state["mat_low_id"]
    payload = {
        "supplier_name": "TEST_Supplier_ABC",
        "job_id": job_id,
        "items": [
            {"material_id": mid, "description": "Shingle bundles", "quantity": 40, "unit": "bundle", "unit_cost": 25.50},
            {"material_id": state["mat_ok_id"], "description": "Nail boxes", "quantity": 5, "unit": "box", "unit_cost": 12},
        ],
    }
    r = requests.post(f"{API}/purchase-orders", json=payload, headers=owner_headers, timeout=15)
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["number"].startswith("PO-")
    # 40*25.50 + 5*12 = 1020 + 60 = 1080
    assert po["total"] == 1080.00
    assert po["status"] == "draft"
    assert po["supplier_name"] == "TEST_Supplier_ABC"
    assert len(po["items"]) == 2
    state["po_id"] = po["id"]
    state["po_line_shingle"] = next(it["id"] for it in po["items"] if it["material_id"] == mid)
    state["po_line_nails"] = next(it["id"] for it in po["items"] if it["material_id"] == state["mat_ok_id"])
    state["mat_low_qty_before_receive"] = 25  # from earlier adjust test
    state["mat_ok_qty_before_receive"] = 20


def test_list_and_get_po(owner_headers, state, job_id):
    lr = requests.get(f"{API}/purchase-orders", headers=owner_headers, timeout=15)
    assert lr.status_code == 200
    assert any(p["id"] == state["po_id"] for p in lr.json())

    # filter by job_id
    fr = requests.get(f"{API}/purchase-orders", params={"job_id": job_id}, headers=owner_headers, timeout=15)
    assert fr.status_code == 200
    ids = {p["id"] for p in fr.json()}
    assert state["po_id"] in ids

    gr = requests.get(f"{API}/purchase-orders/{state['po_id']}", headers=owner_headers, timeout=15)
    assert gr.status_code == 200
    assert gr.json()["id"] == state["po_id"]


# ------------------ Receiving (partial + full + idempotent) ------------------
def test_receive_partial(owner_headers, state):
    key = f"recv-partial-{uuid.uuid4().hex}"
    headers = {**owner_headers, "Idempotency-Key": key}
    payload = {"items": [{"po_item_id": state["po_line_shingle"], "quantity": 10}]}
    r = requests.post(f"{API}/purchase-orders/{state['po_id']}/receive", json=payload, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "partially_received"
    line = next(it for it in po["items"] if it["id"] == state["po_line_shingle"])
    assert line["received_quantity"] == 10

    # Material qty increased by 10
    mr = requests.get(f"{API}/materials", headers=owner_headers, timeout=15)
    mat = next(m for m in mr.json() if m["id"] == state["mat_low_id"])
    assert mat["quantity_on_hand"] == state["mat_low_qty_before_receive"] + 10
    state["idem_partial_key"] = key


def test_receive_partial_idempotent_no_double_count(owner_headers, state):
    """Repeat with SAME key -> no additional inventory."""
    headers = {**owner_headers, "Idempotency-Key": state["idem_partial_key"]}
    payload = {"items": [{"po_item_id": state["po_line_shingle"], "quantity": 10}]}
    r = requests.post(f"{API}/purchase-orders/{state['po_id']}/receive", json=payload, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    # Material qty must still be +10, not +20
    mr = requests.get(f"{API}/materials", headers=owner_headers, timeout=15)
    mat = next(m for m in mr.json() if m["id"] == state["mat_low_id"])
    assert mat["quantity_on_hand"] == state["mat_low_qty_before_receive"] + 10, \
        f"double-counted! expected {state['mat_low_qty_before_receive']+10}, got {mat['quantity_on_hand']}"


def test_receive_remaining_becomes_fully_received(owner_headers, state):
    """Receive the remaining 30 shingles and all 5 nails."""
    key = f"recv-full-{uuid.uuid4().hex}"
    headers = {**owner_headers, "Idempotency-Key": key}
    payload = {"items": [
        {"po_item_id": state["po_line_shingle"], "quantity": 30},
        {"po_item_id": state["po_line_nails"], "quantity": 5},
    ]}
    r = requests.post(f"{API}/purchase-orders/{state['po_id']}/receive", json=payload, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "received", f"expected 'received', got {po['status']}"
    for it in po["items"]:
        assert it["received_quantity"] == it["quantity"], f"line {it['id']} not fully received"

    # Inventory reflects full receipt
    mr = requests.get(f"{API}/materials", headers=owner_headers, timeout=15)
    low = next(m for m in mr.json() if m["id"] == state["mat_low_id"])
    ok = next(m for m in mr.json() if m["id"] == state["mat_ok_id"])
    assert low["quantity_on_hand"] == state["mat_low_qty_before_receive"] + 40
    assert ok["quantity_on_hand"] == state["mat_ok_qty_before_receive"] + 5


def test_receive_over_quantity_rejected(owner_headers, state):
    """After full receipt, further receive should error out (nothing remaining)."""
    key = f"recv-over-{uuid.uuid4().hex}"
    headers = {**owner_headers, "Idempotency-Key": key}
    payload = {"items": [{"po_item_id": state["po_line_shingle"], "quantity": 1}]}
    r = requests.post(f"{API}/purchase-orders/{state['po_id']}/receive", json=payload, headers=headers, timeout=15)
    assert r.status_code == 400, f"expected 400 over-receive, got {r.status_code}: {r.text}"


# ------------------ RBAC ------------------
def test_rbac_sales_blocked_material_create(sales_headers):
    r = requests.post(f"{API}/materials", json={"name": "TEST_SalesBlocked_Mat", "unit": "each"}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


def test_rbac_sales_blocked_job_patch(sales_headers, job_id):
    r = requests.patch(f"{API}/jobs/{job_id}", json={"schedule_notes": "hack"}, headers=sales_headers, timeout=15)
    assert r.status_code == 403


def test_rbac_sales_blocked_po_create_and_receive(sales_headers, job_id, state):
    r = requests.post(f"{API}/purchase-orders", json={"job_id": job_id, "items": []}, headers=sales_headers, timeout=15)
    assert r.status_code == 403
    rr = requests.post(f"{API}/purchase-orders/{state['po_id']}/receive", json={"items": []}, headers=sales_headers, timeout=15)
    assert rr.status_code == 403


def test_rbac_sales_can_list_materials(sales_headers):
    r = requests.get(f"{API}/materials", headers=sales_headers, timeout=15)
    assert r.status_code == 200
