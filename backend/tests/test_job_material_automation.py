"""Job Material Automation & Smart Purchasing regression (requests-based integration)."""
import os
import uuid
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}


def _h():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _material_with_supplier(h):
    d = requests.get(f"{API}/materials", headers=h, timeout=20).json()
    return next(m["id"] for m in d if m.get("primary_supplier_name"))


def _customer(h):
    d = requests.get(f"{API}/customers", headers=h, timeout=20).json()
    return (d[0]["id"] if isinstance(d, list) else d["items"][0]["id"])


def _accepted_job(h):
    mid, cid = _material_with_supplier(h), _customer(h)
    est = requests.post(f"{API}/estimates", headers=h, timeout=20, json={
        "customer_id": cid, "tax_rate": 0,
        "items": [{"material_id": mid, "line_kind": "material", "measured_quantity": 50, "waste_percent": 10,
                   "unit": "SQ", "material_cost": 100, "markup_percent": 20, "pricing_mode": "markup"}]}).json()
    q = requests.post(f"{API}/quotes", headers=h, timeout=20, json={"estimate_id": est["id"]}).json()
    job = requests.post(f"{API}/quotes/{q['id']}/accept", headers=h, timeout=20, json={"acceptance_name": "T"}).json()
    return job["job_id"], mid


def test_generate_from_quote_idempotent():
    h = _h()
    job, _ = _accepted_job(h)
    r1 = requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20).json()
    assert r1["created"] == 1
    r2 = requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20).json()
    assert r2["created"] == 0 and r2["skipped"] == 1  # idempotent, no duplicate rows


def test_required_uses_snapshot_waste():
    h = _h()
    job, _ = _accepted_job(h)
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    plan = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()
    assert plan["materials"][0]["required"] == 55.0  # 50 * 1.10 waste snapshot


def test_reservation_does_not_change_on_hand():
    h = _h()
    job, _ = _accepted_job(h)
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    plan = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()
    jm = plan["materials"][0]
    on_hand_before = jm["on_hand"]
    available_before = jm["available"]
    res = requests.post(f"{API}/jobs/{job}/materials/{jm['id']}/reserve", headers=h, timeout=20, json={}).json()
    assert res["on_hand"] == on_hand_before                       # On Hand unchanged by reservation
    assert res["available"] == round(available_before - res["reserved"], 3)  # available drops by reserved
    assert res["shortage"] == round(max(55.0 - res["reserved"], 0), 3)
    rel = requests.post(f"{API}/jobs/{job}/materials/{jm['id']}/release", headers=h, timeout=20).json()
    assert rel["reserved"] == 0.0                                 # per-job reservation released


def test_purchase_proposal_shows_shortage_and_suppliers():
    h = _h()
    job, _ = _accepted_job(h)
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    prop = requests.get(f"{API}/jobs/{job}/purchase-proposal", headers=h, timeout=20).json()
    assert len(prop["lines"]) >= 1
    line = prop["lines"][0]
    assert line["shortage"] > 0
    assert line["suggested_quantity"] == line["shortage"]
    assert len(line["suppliers"]) >= 1
    assert line["preferred"] is not None


def test_reorder_suggestions_endpoint():
    h = _h()
    r = requests.get(f"{API}/inventory/reorder-suggestions", headers=h, timeout=20)
    assert r.status_code == 200
    for s in r.json()["suggestions"]:
        assert s["projected"] < s["reorder_threshold"]     # only below-threshold
        assert s["recommended_quantity"] >= 0


def test_incoming_only_counts_job_linked_po():
    """A PO NOT linked to the job must not reduce that job's shortage."""
    h = _h()
    job, mid = _accepted_job(h)
    requests.post(f"{API}/jobs/{job}/materials/generate", headers=h, timeout=20)
    before = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]["shortage"]
    # create a PO for the SAME material but NOT linked to the job
    sup = requests.get(f"{API}/suppliers", headers=h, timeout=20).json()
    sid = next(s["id"] for s in sup if s["integration_provider"] != "abc_supply")
    requests.post(f"{API}/purchase-orders", headers=h, timeout=20, json={
        "supplier_id": sid, "items": [{"material_id": mid, "description": "x", "quantity": 999, "unit": "ea", "unit_cost": 1}]})
    after = requests.get(f"{API}/jobs/{job}/material-plan", headers=h, timeout=20).json()["materials"][0]["shortage"]
    assert after == before  # unrelated company-wide PO does NOT satisfy the job
