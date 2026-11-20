# Round 3 retest (iteration 122): EstimateOut.locked flag (owner+sales), unlocked estimates still save (owner + sales own lead), lock blocks PUT
import os, uuid, pytest, requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
SALES = {"email": "sales_bk@example.com", "password": "SalesBk#2026"}
EST_1041 = "61cd2edb-3ca3-4020-9098-b69d3509d664"


def _login(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code != 200:
        pytest.skip(f"login failed {creds['email']}")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def owner():
    return _login(OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(SALES)


@pytest.fixture(scope="module")
def cleanup(owner):
    ids = {"estimates": [], "quotes": []}
    yield ids
    for q in ids["quotes"]:
        owner.delete(f"{BASE_URL}/api/quotes/{q}")
    for e in ids["estimates"]:
        owner.delete(f"{BASE_URL}/api/estimates/{e}")


def _mk_lead(s, who):
    r = s.post(f"{BASE_URL}/api/mobile/leads", json={"name": f"TEST_R3i122_{who}_{uuid.uuid4().hex[:6]}", "address": "1 Test St", "phone": "555-000-0000", "email": "test@example.com"})
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]
    s.post(f"{BASE_URL}/api/customers/from-lead/{lid}")
    return lid, s.get(f"{BASE_URL}/api/leads/{lid}").json().get("customer_id")


def _save(s, e, items):
    return s.put(f"{BASE_URL}/api/estimates/{e['id']}", json={"lead_id": e["lead_id"], "customer_id": e["customer_id"], "tax_rate": e.get("tax_rate") or 0, "items": items},
                 headers={"If-Match": str(e["version"])})


def test_est1041_locked_owner(owner):
    r = owner.get(f"{BASE_URL}/api/estimates/{EST_1041}")
    assert r.status_code == 200, r.text
    assert r.json()["number"] == "EST-1041"
    assert r.json()["locked"] is True


def test_est1041_locked_sales(sales):
    r = sales.get(f"{BASE_URL}/api/estimates/{EST_1041}")
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True
    assert r.json().get("can_see_cost") is False


def test_owner_unlocked_edit_save_then_lock(owner, cleanup):
    lid, cust = _mk_lead(owner, "own")
    r = owner.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0, "items": [{"description": "TEST_a", "quantity": 1, "unit": "ea", "selling_unit_price": 10}]})
    assert r.status_code in (200, 201), r.text
    e = r.json(); cleanup["estimates"].append(e["id"])
    assert e["locked"] is False
    items = [{"id": i["id"], "description": i["description"], "quantity": 3, "unit": i["unit"], "selling_unit_price": 20} for i in e["items"]]
    r = _save(owner, e, items)
    assert r.status_code == 200, r.text
    g = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert g["total"] == 60 and g["locked"] is False
    q = owner.post(f"{BASE_URL}/api/quotes", json={"estimate_id": e["id"]}).json()
    assert owner.post(f"{BASE_URL}/api/quotes/{q['id']}/accept", json={"acceptance_name": "TEST User"}).status_code in (200, 201)
    g = owner.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert g["locked"] is True
    assert _save(owner, g, items).status_code == 409
    # list endpoint consistency
    lst = owner.get(f"{BASE_URL}/api/estimates", params={"lead_id": lid})
    if lst.status_code == 200 and isinstance(lst.json(), list):
        row = [x for x in lst.json() if x["id"] == e["id"]]
        if row:
            assert row[0].get("locked") is True


def test_sales_own_lead_unlocked_edit_save(sales, cleanup):
    lid, cust = _mk_lead(sales, "sales")
    r = sales.post(f"{BASE_URL}/api/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0, "items": [{"description": "TEST_s", "quantity": 1, "unit": "ea", "selling_unit_price": 15}]})
    assert r.status_code in (200, 201), r.text
    e = r.json(); cleanup["estimates"].append(e["id"])
    assert e["locked"] is False
    items = [{"id": i["id"], "description": "TEST_s2", "quantity": 2, "unit": i["unit"], "selling_unit_price": 15} for i in e["items"]]
    r = _save(sales, e, items)
    assert r.status_code == 200, r.text
    g = sales.get(f"{BASE_URL}/api/estimates/{e['id']}").json()
    assert g["total"] == 30 and g["items"][0]["description"] == "TEST_s2" and g["locked"] is False
