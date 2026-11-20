"""Estimate line-identity contract + sales estimate authorization (Round 3 closeout).

Legacy (no line ids) saves: allowed when the estimate has no takeoff-created lines; refused atomically (409)
when it has them. Current clients (line_ids / ids) save normally and keep takeoff links.
"""
import os, uuid, pytest, requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}
FIELDS = ("description", "unit", "measured_quantity", "waste_percent", "material_cost", "markup_percent",
          "selling_unit_price", "line_kind", "material_id", "assembly_id", "assembly_version", "assembly_name")
MSG = "This estimate contains items calculated from roof measurements. Update the app or edit this estimate in RoofSpan Office."


def _session(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code != 200:
        pytest.skip(f"login failed for {creds['email']}")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    s.me = s.get(f"{BASE_URL}/api/auth/me").json()
    return s


@pytest.fixture(scope="module")
def owner():
    return _session(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _session(SALES)


def _lead(owner):
    lid = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_LID_{uuid.uuid4().hex[:6]}", "address": "1 Test St",
                                                            "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
    owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    return lid, owner.get(f"{BASE_URL}/api/leads/{lid}").json()["customer_id"]


def _verified_measurement(owner, lid, area=2000):
    rev = owner.post(f"{BASE_URL}/api/measurements", json={"lead_id": lid, "source": "office",
        "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": area}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()["id"]
    for to in ("field_complete", "office_verified"):
        assert owner.post(f"{BASE_URL}/api/measurements/{rev}/status", json={"to": to}).status_code == 200
    return rev


def _template(owner):
    tpl = [t for t in owner.get(f"{BASE_URL}/api/takeoff/templates", params={"active": True}).json() if t.get("latest_revision")]
    if not tpl:
        pytest.skip("no takeoff template")
    return tpl[0]["latest_revision"]["id"]


def _body(rev, tpl):
    return {"measurement_revision_id": rev, "template_revision_id": tpl, "estimate_waste_override": None,
            "drip_edge_override_lf": None, "structure_waste_overrides": {}, "replace_modified_generated": False}


def _get(s, eid):
    return s.get(f"{BASE_URL}/api/estimates/{eid}").json()


def _put(s, e, items, **extra):
    return s.put(f"{BASE_URL}/api/estimates/{e['id']}", headers={"If-Match": str(e["version"])},
                 json={"lead_id": e["lead_id"], "customer_id": e["customer_id"], "tax_rate": e["tax_rate"], "items": items, **extra})


def _legacy(items):
    return [{k: i.get(k) for k in FIELDS} for i in items]


@pytest.fixture(scope="module")
def takeoff_est(owner):
    lid, cust = _lead(owner)
    rev, tpl = _verified_measurement(owner, lid), _template(owner)
    eid = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0,
                     "items": [{"description": "Manual A", "unit": "EA", "measured_quantity": 1, "selling_unit_price": 10}]}).json()["id"]
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json=_body(rev, tpl)).status_code == 200
    yield {"eid": eid, "lid": lid, "body": _body(rev, tpl)}
    owner.delete(f"{BASE_URL}/api/estimates/{eid}")


def test_legacy_save_without_takeoff_lines_succeeds(owner):
    lid, cust = _lead(owner)
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0,
                   "items": [{"description": "A", "unit": "EA", "measured_quantity": 1, "selling_unit_price": 5}]}).json()
    items = [{"description": "Top", "unit": "EA", "measured_quantity": 2, "selling_unit_price": 3}] + _legacy(e["items"])
    r = _put(owner, e, items)
    assert r.status_code == 200, r.text
    assert [i["description"] for i in r.json()["items"]] == ["Top", "A"]
    owner.delete(f"{BASE_URL}/api/estimates/{e['id']}")


def test_legacy_save_with_takeoff_lines_refused_atomically(owner, takeoff_est):
    eid = takeoff_est["eid"]
    before = _get(owner, eid)
    gen_before = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=takeoff_est["body"]).json()["generated_line_ids_to_replace"]
    assert gen_before
    scenarios = [
        [{"description": "Inserted at top", "unit": "EA", "measured_quantity": 1, "selling_unit_price": 1}] + _legacy(before["items"]),
        [dict(i, selling_unit_price=999) if i["description"] == "Manual A" else i for i in _legacy(before["items"])],
        [i for i in _legacy(before["items"]) if i["description"] != "Manual A"],
    ]
    for items in scenarios:
        r = _put(owner, before, items, price_book_id=None, notes="should not apply")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["message"] == MSG
        after = _get(owner, eid)
        assert after["version"] == before["version"] and after["total"] == before["total"] and after["notes"] == before["notes"]
        assert [(i["id"], i["description"], i["selling_unit_price"]) for i in after["items"]] == \
               [(i["id"], i["description"], i["selling_unit_price"]) for i in before["items"]]
    gen_after = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=takeoff_est["body"]).json()["generated_line_ids_to_replace"]
    assert sorted(gen_after) == sorted(gen_before)  # identities + links intact


def test_current_client_with_ids_edits_manual_lines_and_keeps_links(owner, takeoff_est):
    eid = takeoff_est["eid"]
    e = _get(owner, eid)
    gen = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=takeoff_est["body"]).json()["generated_line_ids_to_replace"]
    full = [{**{k: i.get(k) for k in FIELDS}, "id": i["id"]} for i in e["items"]]
    manual = [i for i in full if i["id"] not in gen]
    generated = [i for i in full if i["id"] in gen]
    new_manual = [dict(i, selling_unit_price=11) for i in manual]  # change manual line
    items = [{"description": "Top manual", "unit": "EA", "measured_quantity": 1, "selling_unit_price": 2}] + new_manual + generated
    r = _put(owner, e, items, line_ids=True)
    assert r.status_code == 200, r.text
    out = r.json()["items"]
    assert out[0]["description"] == "Top manual"
    assert {i["id"] for i in out} >= set(gen)
    # remove a manual line
    e2 = r.json()
    items2 = [{**{k: i.get(k) for k in FIELDS}, "id": i["id"]} for i in e2["items"] if i["description"] != "Top manual"]
    r2 = _put(owner, e2, items2, line_ids=True)
    assert r2.status_code == 200, r2.text
    p = owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/preview", json=takeoff_est["body"]).json()
    assert sorted(p["generated_line_ids_to_replace"]) == sorted(gen)
    n = len(r2.json()["items"])
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json=takeoff_est["body"]).status_code == 200
    final = _get(owner, eid)
    assert len(final["items"]) == n  # re-run replaces, no duplicates
    assert any(i["description"] == "Manual A" for i in final["items"])


def test_office_can_still_edit_after_refusal(owner, takeoff_est):
    e = _get(owner, takeoff_est["eid"])
    items = [{**{k: i.get(k) for k in FIELDS}, "id": i["id"]} for i in e["items"]]
    assert _put(owner, e, items, line_ids=True).status_code == 200


def test_sales_blocked_on_unassigned_estimate(owner, sales, takeoff_est):
    eid = takeoff_est["eid"]  # lead not assigned to sales
    assert sales.get(f"{BASE_URL}/api/estimates/{eid}").status_code == 403
    e = _get(owner, eid)
    assert _put(sales, e, [], line_ids=True).status_code == 403
    for path in ("/duplicate", "/price-book/preview"):
        assert sales.post(f"{BASE_URL}/api/estimates/{eid}{path}", json={"price_book_id": None}).status_code in (403, 422)
    assert sales.get(f"{BASE_URL}/api/estimates/{eid}/cost-refresh/preview").status_code == 403
    assert sales.delete(f"{BASE_URL}/api/estimates/{eid}").status_code == 403
    assert sales.get(f"{BASE_URL}/api/takeoff/estimates/{eid}/status").status_code == 403
    assert eid not in [x["id"] for x in sales.get(f"{BASE_URL}/api/estimates").json()]
    assert eid not in [x["id"] for x in sales.get(f"{BASE_URL}/api/estimates", params={"lead_id": takeoff_est["lid"]}).json()]
    lead = owner.get(f"{BASE_URL}/api/leads/{takeoff_est['lid']}").json()
    assert sales.post(f"{BASE_URL}/api/estimates", json={"lead_id": takeoff_est["lid"], "customer_id": lead["customer_id"], "items": []}).status_code == 403
    assert owner.get(f"{BASE_URL}/api/estimates/{eid}").status_code == 200


def test_sales_allowed_on_assigned_estimate(owner, sales):
    lid, cust = _lead(owner)
    assert owner.put(f"{BASE_URL}/api/leads/{lid}/assign", json={"user_id": sales.me["id"]}).status_code == 200
    r = sales.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": [{"description": "X", "measured_quantity": 1, "selling_unit_price": 4}]})
    assert r.status_code == 201, r.text
    e = r.json()
    assert sales.get(f"{BASE_URL}/api/estimates/{e['id']}").status_code == 200
    assert _put(sales, e, [{**{k: i.get(k) for k in FIELDS}, "id": i["id"]} for i in e["items"]], line_ids=True).status_code == 200
    assert e["id"] in [x["id"] for x in sales.get(f"{BASE_URL}/api/estimates", params={"lead_id": lid}).json()]


def test_remeasure_baseline_ignores_unverified_draft(owner):
    lid, cust = _lead(owner)
    rev1, tpl = _verified_measurement(owner, lid, 2000), _template(owner)
    eid = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": []}).json()["id"]
    assert owner.post(f"{BASE_URL}/api/takeoff/estimates/{eid}/apply", json=_body(rev1, tpl)).status_code == 200
    # newer DRAFT only -> not a change, reported as pending
    draft = owner.post(f"{BASE_URL}/api/measurements", json={"lead_id": lid, "source": "office",
        "structures": [{"ref": "s1", "name": "Main", "structure_type": "main_house", "stories": 1}],
        "facets": [{"ref": "F1", "structure_ref": "s1", "facet_label": "F1", "pitch_rise": 6, "area_sqft": 2600}],
        "edges": [{"edge_type": "eave", "length_ft": 100, "facet_ref": "F1"}], "summary": {}}).json()
    st = owner.get(f"{BASE_URL}/api/takeoff/estimates/{eid}/status").json()
    assert st["measurements_changed"] is False and st["changed_metrics"] == []
    assert st["pending_unverified_revision_number"] == draft["revision_number"]
    owner.delete(f"{BASE_URL}/api/estimates/{eid}")
