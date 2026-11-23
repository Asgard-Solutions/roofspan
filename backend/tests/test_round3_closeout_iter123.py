"""Iteration 123: Round 3 closeout extra checks (sales authz on apply endpoints, re-measure verified baseline,
lock bypass via price-book/cost-refresh apply, existing data, default price book)."""
import os, uuid, pytest, requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}
EST_1041 = "61cd2edb-3ca3-4020-9098-b69d3509d664"


def _session(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    s.me = s.get(f"{BASE_URL}/api/auth/me").json()
    return s


@pytest.fixture(scope="module")
def owner():
    return _session(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _session(SALES)


@pytest.fixture(scope="module")
def created(owner):
    ids = {"estimates": [], "quotes": []}
    yield ids
    for q in ids["quotes"]:
        owner.delete(f"{BASE_URL}/api/quotes/{q}")
    for e in ids["estimates"]:
        owner.delete(f"{BASE_URL}/api/estimates/{e}")


def _lead(owner):
    lid = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_I123_{uuid.uuid4().hex[:6]}", "address": "1 Test St",
                                                            "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
    owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    return lid, owner.get(f"{BASE_URL}/api/leads/{lid}").json()["customer_id"]


def _meas(owner, lid, area, verify=True):
    rev = owner.post(f"{BASE_URL}/api/measurements", json={"lead_id": lid, "source": "office",
        "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": area}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()
    if verify:
        for to in ("field_complete", "office_verified"):
            assert owner.post(f"{BASE_URL}/api/measurements/{rev['id']}/status", json={"to": to}).status_code == 200
    return rev


def _tpl(owner):
    t = [t for t in owner.get(f"{BASE_URL}/api/takeoff/templates", params={"active": True}).json() if t.get("latest_revision")]
    return t[0]["latest_revision"]["id"]


def _body(rev, tpl):
    return {"measurement_revision_id": rev, "template_revision_id": tpl, "estimate_waste_override": None,
            "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}


def _pb(owner):
    return [p for p in owner.get(f"{BASE_URL}/api/estimating/price-books").json()]


# Sales authz: apply endpoints (price-book apply, cost-refresh apply) on unassigned lead
def test_sales_apply_endpoints_forbidden(owner, sales, created):
    lid, cust = _lead(owner)
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": [
        {"description": "TEST line", "measured_quantity": 1, "selling_unit_price": 7}]}).json()
    created["estimates"].append(e["id"])
    std = [p for p in _pb(owner) if p["is_default"]][0]["id"]
    eid = e["id"]
    assert sales.post(f"{BASE_URL}/api/estimates/{eid}/price-book/apply", json={"price_book_id": std}).status_code == 403
    assert sales.post(f"{BASE_URL}/api/estimates/{eid}/price-book/preview", json={"price_book_id": std}).status_code == 403
    assert sales.post(f"{BASE_URL}/api/estimates/{eid}/cost-refresh/apply", json={"line_ids": [], "recalc_selling_price": False}).status_code == 403
    assert sales.post(f"{BASE_URL}/api/estimates/{eid}/duplicate").status_code == 403
    assert sales.get(f"{BASE_URL}/api/estimates/{eid}/cost-refresh/preview").status_code == 403
    after = owner.get(f"{BASE_URL}/api/estimates/{eid}").json()
    assert after["version"] == e["version"]
    # owner unaffected
    assert owner.post(f"{BASE_URL}/api/estimates/{eid}/price-book/preview", json={"price_book_id": std}).status_code == 200
    d = owner.post(f"{BASE_URL}/api/estimates/{eid}/duplicate")
    assert d.status_code == 201
    created["estimates"].append(d.json()["id"])


# Default price book is Standard on new estimate
def test_default_price_book_standard(owner, created):
    pbs = _pb(owner)
    pbs = [p for p in pbs if p["is_default"]]  # other run-created books may exist; the company default is "Standard"
    assert [p["name"] for p in pbs] == ["Standard"]
    lid, cust = _lead(owner)
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": []}).json()
    created["estimates"].append(e["id"])
    assert e["price_book_id"] == pbs[0]["id"]


# Re-measure: newer VERIFIED -> changed, even if newer draft also exists
def test_remeasure_verified_newer_detected_with_draft_on_top(owner, created):
    lid, cust = _lead(owner)
    r1 = _meas(owner, lid, 2000)
    tpl = _tpl(owner)
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": []}).json()
    created["estimates"].append(e["id"])
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{e['id']}/apply", json=_body(r1["id"], tpl)).status_code == 200
    d1 = _meas(owner, lid, 2600, verify=False)
    st = owner.get(f"{BASE_URL}/api/takeoff/estimates/{e['id']}/status").json()
    assert st["measurements_changed"] is False and st["changed_metrics"] == []
    assert st["pending_unverified_revision_number"] == d1["revision_number"]
    # verify the draft -> becomes changed
    for to in ("field_complete", "office_verified"):
        assert owner.post(f"{BASE_URL}/api/measurements/{d1['id']}/status", json={"to": to}).status_code == 200
    d2 = _meas(owner, lid, 3200, verify=False)  # even newer draft
    st = owner.get(f"{BASE_URL}/api/takeoff/estimates/{e['id']}/status").json()
    assert st["measurements_changed"] is True, st
    assert st["latest_measurement_revision_id"] == d1["id"]
    m = {c["metric"]: c for c in st["changed_metrics"]}
    area = [c for k, c in m.items() if "area" in k]
    assert area and any(c["to"] in (2600, 2600.0) for c in area), st["changed_metrics"]
    assert not any(c["to"] in (3200, 3200.0) for c in st["changed_metrics"])
    assert st["pending_unverified_revision_number"] == d2["revision_number"]
    print("STATUS", st)


# Lock: accepted estimate must not be changed via price-book/apply or cost-refresh/apply (owner)
def test_locked_estimate_apply_endpoints(owner, created):
    lid, cust = _lead(owner)
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": [
        {"description": "TEST line", "measured_quantity": 1, "selling_unit_price": 7}]}).json()
    created["estimates"].append(e["id"])
    q = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": e["id"]}).json()
    assert owner.post(f"{BASE_URL}/api/quotes/{q['id']}/accept", json={"acceptance_name": "TEST User"}).status_code in (200, 201)
    before = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert before["locked"] is True
    std = [p for p in _pb(owner) if p["is_default"]][0]["id"]
    r1 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/price-book/apply", json={"price_book_id": std})
    r2 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/cost-refresh/apply", json={"line_ids": [], "recalc_selling_price": False})
    after = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    print("price-book/apply", r1.status_code, "cost-refresh/apply", r2.status_code, "version", before["version"], "->", after["version"])
    assert r1.status_code == 409 and r2.status_code == 409 and after["version"] == before["version"]


# Existing data: EST-1041 opens unchanged
def test_est_1041_opens(owner):
    e = owner.get(f"{BASE_URL}/api/estimates/{EST_1041}").json()
    assert e["number"] == "EST-1041" and e["locked"] is True
    print("EST-1041", e["total"], e["subtotal"], e["version"], len(e["items"]))
