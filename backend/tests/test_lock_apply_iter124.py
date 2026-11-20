"""Iteration 124: accepted-quote lock on price-book/apply + cost-refresh/apply; unlocked still works."""
import os, uuid, pytest, requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
MSG = "This estimate has an accepted quote and can no longer be edited."


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=OWNER)
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def created(owner):
    ids = []
    yield ids
    for e in ids:
        owner.delete(f"{BASE_URL}/api/estimates/{e}")


def _est(owner, created):
    lid = owner.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_I124_{uuid.uuid4().hex[:6]}", "address": "1 Test St",
                                                            "phone": "555-000-0000", "email": "test@example.com"}).json()["id"]
    owner.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    cust = owner.get(f"{BASE_URL}/api/leads/{lid}").json()["customer_id"]
    e = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "items": [
        {"description": "TEST line", "measured_quantity": 2, "selling_unit_price": 7}]}).json()
    created.append(e["id"])
    return e


def _std(owner):
    return [p for p in owner.get(f"{BASE_URL}/api/estimating/price-books").json() if p["is_default"]][0]["id"]


# Locked: both apply endpoints 409 and nothing changes
def test_locked_apply_409_atomic(owner, created):
    e = _est(owner, created)
    q = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": e["id"]}).json()
    assert owner.post(f"{BASE_URL}/api/quotes/{q['id']}/accept", json={"acceptance_name": "TEST User"}).status_code in (200, 201)
    before = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert before["locked"] is True
    line_ids = [i["id"] for i in before["items"]]
    r1 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/price-book/apply", json={"price_book_id": _std(owner)})
    r2 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/cost-refresh/apply", json={"line_ids": line_ids, "recalc_selling_price": True})
    r3 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/cost-refresh/apply", json={"line_ids": [], "recalc_selling_price": False})
    for r in (r1, r2, r3):
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == MSG
    after = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert after["version"] == before["version"]
    assert after["total"] == before["total"] and after["subtotal"] == before["subtotal"]
    assert after["price_book_id"] == before["price_book_id"]
    strip = lambda its: [{k: v for k, v in i.items() if k != "updated_at"} for i in its]
    assert strip(after["items"]) == strip(before["items"])


# Locked EST-1041 seeded estimate: 409 too, unchanged
def test_est1041_locked_409(owner):
    eid = "61cd2edb-3ca3-4020-9098-b69d3509d664"
    before = owner.get(f"{BASE_URL}/api/estimates/{eid}").json()
    assert before["locked"] is True
    r1 = owner.post(f"{BASE_URL}/api/estimates/{eid}/price-book/apply", json={"price_book_id": _std(owner)})
    r2 = owner.post(f"{BASE_URL}/api/estimates/{eid}/cost-refresh/apply", json={"line_ids": [], "recalc_selling_price": False})
    assert r1.status_code == 409 and r2.status_code == 409
    after = owner.get(f"{BASE_URL}/api/estimates/{eid}").json()
    assert after["version"] == before["version"] and after["total"] == before["total"]


# Unlocked: both apply endpoints still 200
def test_unlocked_apply_200(owner, created):
    e = _est(owner, created)
    v0 = e["version"]
    line_ids = [i["id"] for i in e["items"]]
    r1 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/price-book/apply", json={"price_book_id": _std(owner)})
    assert r1.status_code == 200, r1.text
    assert r1.json()["version"] == v0 + 1 and r1.json()["price_book_id"] == _std(owner)
    r2 = owner.post(f"{BASE_URL}/api/estimates/{e['id']}/cost-refresh/apply", json={"line_ids": line_ids, "recalc_selling_price": False})
    assert r2.status_code == 200, r2.text
    assert r2.json()["version"] == v0 + 2
    got = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert got["version"] == v0 + 2 and got["total"] == r2.json()["total"]
