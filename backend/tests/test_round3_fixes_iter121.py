# Round 3 retest (iteration 121): line-id reuse on estimate save, takeoff re-apply/replace, accepted-quote lock on apply, quotes/invoices with LineItemIn.id
import os, uuid, pytest, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
ITEM_KEYS = ("id", "description", "unit", "quantity", "measured_quantity", "waste_percent", "material_cost", "markup_percent",
             "selling_unit_price", "line_kind", "material_id", "assembly_id", "assembly_version", "assembly_name")


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=OWNER)
    if r.status_code != 200:
        pytest.skip("owner login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def ctx(owner):
    tpl = [t for t in owner.get(f"{BASE_URL}/api/takeoff/templates", params={"active": True}).json() if t.get("latest_revision")]
    if not tpl:
        pytest.skip("no takeoff template")
    lid = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_R3i121_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
    owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    cust = owner.get(f"{BASE_URL}/api/leads/{lid}").json()["customer_id"]
    rev = owner.post(f"{BASE_URL}/api/measurements", json={"lead_id": lid, "source": "office",
        "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 2000}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()["id"]
    for to in ("field_complete", "office_verified"):
        assert owner.post(f"{BASE_URL}/api/measurements/{rev}/status", json={"to": to}).status_code == 200
    body = {"measurement_revision_id": rev, "template_revision_id": tpl[0]["latest_revision"]["id"], "estimate_waste_override": None,
            "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}
    c = {"lead": lid, "cust": cust, "body": body, "estimates": [], "quotes": []}
    yield c
    for q in c["quotes"]:
        owner.delete(f"{BASE_URL}/api/quotes/{q}")
    for e in c["estimates"]:
        owner.delete(f"{BASE_URL}/api/estimates/{e}")


def _new_est(owner, ctx, items=()):
    r = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": ctx["lead"], "customer_id": ctx["cust"], "tax_rate": 0, "items": list(items)})
    assert r.status_code in (200, 201), r.text
    ctx["estimates"].append(r.json()["id"])
    return r.json()["id"]


def _get(owner, eid):
    return owner.get(f"{BASE_URL}/api/estimates/{eid}").json()


def _save(owner, e, items):
    return owner.put(f"{BASE_URL}/api/estimates/{e['id']}", json={"lead_id": e["lead_id"], "customer_id": e["customer_id"], "tax_rate": 0, "items": items},
                     headers={"If-Match": str(e["version"])})


def _apply(owner, eid, body, **kw):
    return owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json={**body, **kw})


def test_edit_price_with_ids_then_review_and_replace_no_dup(owner, ctx):
    custom = {"description": "TEST_custom gutter", "quantity": 2, "unit": "ea", "selling_unit_price": 50}
    eid = _new_est(owner, ctx, [custom])
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    e = _get(owner, eid)
    n1 = len(e["items"]); ids1 = {i["id"] for i in e["items"]}
    assert n1 >= 2
    items = [{k: i.get(k) for k in ITEM_KEYS} for i in e["items"]]
    for i in items:
        if i["description"] != custom["description"]:
            i["selling_unit_price"] = 77
    r = _save(owner, e, items)
    assert r.status_code == 200, r.text
    e2 = _get(owner, eid)
    assert {i["id"] for i in e2["items"]} == ids1, "line ids should be reused on save"
    p = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=ctx["body"]).json()
    assert p["generated_line_ids_to_replace"] and p["review_required"] is True
    r = _apply(owner, eid, ctx["body"])
    assert r.status_code == 409, r.text
    r = _apply(owner, eid, ctx["body"], replace_modified_generated=True)
    assert r.status_code == 200, r.text
    e3 = _get(owner, eid)
    assert len(e3["items"]) == n1, [i["description"] for i in e3["items"]]
    assert any(i["description"] == custom["description"] for i in e3["items"]), "custom line lost"


def test_save_without_ids_no_edit_then_reapply_no_dup(owner, ctx):
    eid = _new_est(owner, ctx)
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    e = _get(owner, eid); n1 = len(e["items"])
    items = [{k: i.get(k) for k in ITEM_KEYS if k != "id"} for i in e["items"]]
    assert _save(owner, e, items).status_code == 200
    p = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=ctx["body"]).json()
    assert p["generated_line_ids_to_replace"] and not p["review_required"]
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    assert len(_get(owner, eid)["items"]) == n1


def test_add_custom_line_with_ids_then_reapply_keeps_custom(owner, ctx):
    eid = _new_est(owner, ctx)
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    e = _get(owner, eid); n1 = len(e["items"])
    items = [{"description": "TEST_hand line", "quantity": 1, "unit": "ea", "selling_unit_price": 10}] + [{k: i.get(k) for k in ITEM_KEYS} for i in e["items"]]
    assert _save(owner, e, items).status_code == 200
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    e3 = _get(owner, eid)
    assert len(e3["items"]) == n1 + 1
    assert any(i["description"] == "TEST_hand line" for i in e3["items"])


def test_foreign_id_is_not_reused(owner, ctx):
    a = _new_est(owner, ctx, [{"description": "TEST_A", "quantity": 1, "selling_unit_price": 1}])
    b = _new_est(owner, ctx, [{"description": "TEST_B", "quantity": 1, "selling_unit_price": 1}])
    aid = _get(owner, a)["items"][0]["id"]
    eb = _get(owner, b)
    r = _save(owner, eb, [{"id": aid, "description": "TEST_B2", "quantity": 1, "selling_unit_price": 1}])
    assert r.status_code == 200, r.text
    assert _get(owner, b)["items"][0]["id"] != aid
    assert _get(owner, a)["items"][0]["description"] == "TEST_A"


def test_duplicate_ids_in_payload(owner, ctx):
    eid = _new_est(owner, ctx, [{"description": "TEST_D", "quantity": 1, "selling_unit_price": 5}])
    e = _get(owner, eid); lid = e["items"][0]["id"]
    r = _save(owner, e, [{"id": lid, "description": "TEST_D", "quantity": 1, "selling_unit_price": 5}, {"id": lid, "description": "TEST_D copy", "quantity": 1, "selling_unit_price": 5}])
    assert r.status_code == 200, r.text
    got = _get(owner, eid)["items"]
    assert len(got) == 2 and len({i["id"] for i in got}) == 2
    assert _get(owner, eid)["total"] == 10


def test_accepted_quote_locks_apply_and_save_and_invoice_created(owner, ctx):
    eid = _new_est(owner, ctx, [{"description": "TEST_lock", "quantity": 2, "unit": "ea", "selling_unit_price": 100}])
    r = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": eid})
    assert r.status_code in (200, 201), r.text
    q = r.json()
    assert q["total"] == 200 and q["items"][0]["quantity"] == 2
    r = owner.post(f"{BASE_URL}/api/quotes/{q['id']}/accept", json={"acceptance_name": "TEST User"})
    assert r.status_code in (200, 201), r.text
    r = _apply(owner, eid, ctx["body"])
    assert r.status_code == 409, r.text
    assert "accepted" in r.text.lower()
    e = _get(owner, eid)
    assert len(e["items"]) == 1
    assert _save(owner, e, [{"description": "x", "quantity": 1, "selling_unit_price": 1}]).status_code == 409
    r = owner.post(f"{BASE_URL}/api/invoices", json={"quote_id": q["id"]})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["total"] == 200 and len(inv["items"]) == 1


def test_manual_quote_with_item_ids_ok(owner, ctx):
    r = owner.post(f"{BASE_URL}/api/quotes", json={"customer_id": ctx["cust"], "tax_rate": 0, "items": [{"id": str(uuid.uuid4()), "description": "TEST_q", "quantity": 3, "unit_price": 10}]})
    assert r.status_code in (200, 201), r.text
    ctx["quotes"].append(r.json()["id"])
    assert r.json()["total"] == 30


@pytest.mark.xfail(reason="known limitation: id-less clients matched by position only", strict=False)
def test_probe_no_ids_insert_at_front_reapply(owner, ctx):
    # Legacy clients (no ids) inserting a line at the top shift positions -> links may be lost -> duplicates (known limitation probe)
    eid = _new_est(owner, ctx)
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    e = _get(owner, eid); n1 = len(e["items"])
    items = [{"description": "TEST_front", "quantity": 1, "selling_unit_price": 1}] + [{k: i.get(k) for k in ITEM_KEYS if k != "id"} for i in e["items"]]
    assert _save(owner, e, items).status_code == 200
    assert _apply(owner, eid, ctx["body"]).status_code == 200
    assert len(_get(owner, eid)["items"]) == n1 + 1
