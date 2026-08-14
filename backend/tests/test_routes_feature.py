"""Backend tests for the Canvassing Routes feature (P0)."""
import os
import uuid
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"

OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES1 = ("sales1_38f545f9@example.com", "Sales1#2026")
SALES2 = ("sales2_7ad4f5cd@example.com", "Sales2#2026")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def owner_tok():
    return _login(*OWNER)


@pytest.fixture(scope="module", autouse=True)
def _ensure_sales_users(owner_tok):
    """Self-seed the two sales accounts so this suite is data-independent (they may not pre-exist on a
    given DB). Creating an existing user returns 409, which is fine."""
    for email, pw in (SALES1, SALES2):
        requests.post(f"{API}/users", headers=_h(owner_tok),
                      json={"email": email, "full_name": email.split("@")[0], "password": pw, "role": "sales"},
                      timeout=15)


@pytest.fixture(scope="module")
def sales1_tok(_ensure_sales_users):
    return _login(*SALES1)


@pytest.fixture(scope="module")
def sales2_tok(_ensure_sales_users):
    return _login(*SALES2)


@pytest.fixture(scope="module")
def sales_ids(owner_tok, _ensure_sales_users):
    r = requests.get(f"{API}/users/assignable", headers=_h(owner_tok), timeout=15)
    assert r.status_code == 200
    users = r.json()
    by_email = {u["email"]: u["id"] for u in users}
    return {"s1": by_email.get(SALES1[0]), "s2": by_email.get(SALES2[0])}


@pytest.fixture(scope="module")
def created_route(owner_tok, sales_ids):
    payload = {
        "name": f"TEST_route_{uuid.uuid4().hex[:8]}",
        "assigned_user_id": sales_ids["s1"],
        "est_miles": 0.5,
        "stops": [
            {"latitude": 40.1, "longitude": -74.1, "sort": 0},
            {"latitude": 40.2, "longitude": -74.2, "sort": 1},
            {"latitude": 40.3, "longitude": -74.3, "sort": 2},
        ],
    }
    r = requests.post(f"{API}/routes", headers=_h(owner_tok), json=payload, timeout=15)
    assert r.status_code == 201, r.text
    route = r.json()
    yield route
    # teardown
    requests.delete(f"{API}/routes/{route['id']}", headers=_h(owner_tok), timeout=15)


# ---------- Create ----------

def test_create_route_returns_detail(created_route, sales_ids):
    r = created_route
    assert r["status"] == "assigned"
    assert r["stop_count"] == 3
    assert r["assigned_user_id"] == sales_ids["s1"]
    assert r["assigned_user_name"]
    assert isinstance(r.get("stops"), list) and len(r["stops"]) == 3
    # sort preserved
    sorts = [s["sort"] for s in r["stops"]]
    assert sorts == sorted(sorts)


def test_sales_cannot_create(sales1_tok):
    r = requests.post(f"{API}/routes", headers=_h(sales1_tok),
                      json={"name": "nope", "stops": [{"latitude": 1, "longitude": 1}]}, timeout=15)
    assert r.status_code == 403


def test_create_requires_stops(owner_tok):
    r = requests.post(f"{API}/routes", headers=_h(owner_tok),
                      json={"name": "empty", "stops": []}, timeout=15)
    assert r.status_code == 422


# ---------- Listing / RBAC visibility ----------

def test_list_manager_sees_route(owner_tok, created_route):
    r = requests.get(f"{API}/routes", headers=_h(owner_tok), timeout=15)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert created_route["id"] in ids
    row = next(x for x in r.json() if x["id"] == created_route["id"])
    for k in ("knocked", "skipped", "pending", "assigned_user_name"):
        assert k in row


def test_list_sales_sees_only_assigned(sales1_tok, sales2_tok, created_route):
    r1 = requests.get(f"{API}/routes", headers=_h(sales1_tok), timeout=15)
    assert r1.status_code == 200
    assert created_route["id"] in [x["id"] for x in r1.json()]

    r2 = requests.get(f"{API}/routes", headers=_h(sales2_tok), timeout=15)
    assert r2.status_code == 200
    assert created_route["id"] not in [x["id"] for x in r2.json()]


def test_get_detail_sales_not_assigned_403(sales2_tok, created_route):
    r = requests.get(f"{API}/routes/{created_route['id']}", headers=_h(sales2_tok), timeout=15)
    assert r.status_code == 403


def test_get_detail_assigned_sales_200(sales1_tok, created_route):
    r = requests.get(f"{API}/routes/{created_route['id']}", headers=_h(sales1_tok), timeout=15)
    assert r.status_code == 200
    assert len(r.json()["stops"]) == 3


# ---------- Assign ----------

def test_assign_invalid_user_422(owner_tok, created_route):
    fake = str(uuid.uuid4())
    r = requests.put(f"{API}/routes/{created_route['id']}/assign", headers=_h(owner_tok),
                     json={"user_id": fake}, timeout=15)
    assert r.status_code == 422


def test_assign_sales_forbidden(sales1_tok, created_route):
    r = requests.put(f"{API}/routes/{created_route['id']}/assign", headers=_h(sales1_tok),
                     json={"user_id": None}, timeout=15)
    assert r.status_code == 403


def test_reassign_and_unassign(owner_tok, created_route, sales_ids):
    rid = created_route["id"]
    r = requests.put(f"{API}/routes/{rid}/assign", headers=_h(owner_tok),
                     json={"user_id": sales_ids["s2"]}, timeout=15)
    assert r.status_code == 200
    assert r.json()["assigned_user_id"] == sales_ids["s2"]

    r2 = requests.put(f"{API}/routes/{rid}/assign", headers=_h(owner_tok),
                      json={"user_id": None}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["assigned_user_id"] is None

    # restore for downstream tests
    requests.put(f"{API}/routes/{rid}/assign", headers=_h(owner_tok),
                 json={"user_id": sales_ids["s1"]}, timeout=15)


# ---------- Stop updates & status transitions ----------

def test_stop_update_and_status_transition(owner_tok, sales1_tok, created_route):
    rid = created_route["id"]
    detail = requests.get(f"{API}/routes/{rid}", headers=_h(owner_tok), timeout=15).json()
    stops = detail["stops"]
    assert detail["status"] == "assigned"

    # Invalid status -> 422
    r_bad = requests.put(f"{API}/routes/{rid}/stops/{stops[0]['id']}", headers=_h(owner_tok),
                        json={"status": "banana"}, timeout=15)
    assert r_bad.status_code == 422

    # Sales rep (assigned) knocks first stop -> in_progress
    r1 = requests.put(f"{API}/routes/{rid}/stops/{stops[0]['id']}", headers=_h(sales1_tok),
                     json={"status": "knocked"}, timeout=15)
    assert r1.status_code == 200
    assert r1.json()["status"] == "in_progress"
    assert r1.json()["knocked"] == 1

    # Knock 2nd, skip 3rd -> completed
    requests.put(f"{API}/routes/{rid}/stops/{stops[1]['id']}", headers=_h(sales1_tok),
                 json={"status": "knocked"}, timeout=15)
    r3 = requests.put(f"{API}/routes/{rid}/stops/{stops[2]['id']}", headers=_h(sales1_tok),
                     json={"status": "skipped"}, timeout=15)
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"

    # Reset one -> back to in_progress
    r4 = requests.put(f"{API}/routes/{rid}/stops/{stops[0]['id']}", headers=_h(sales1_tok),
                     json={"status": "pending"}, timeout=15)
    assert r4.status_code == 200
    assert r4.json()["status"] == "in_progress"


def test_non_assigned_sales_cannot_update_stop(sales2_tok, owner_tok, created_route):
    rid = created_route["id"]
    detail = requests.get(f"{API}/routes/{rid}", headers=_h(owner_tok), timeout=15).json()
    sid = detail["stops"][0]["id"]
    r = requests.put(f"{API}/routes/{rid}/stops/{sid}", headers=_h(sales2_tok),
                     json={"status": "knocked"}, timeout=15)
    assert r.status_code == 403


# ---------- Delete ----------

def test_sales_cannot_delete(sales1_tok, created_route):
    r = requests.delete(f"{API}/routes/{created_route['id']}", headers=_h(sales1_tok), timeout=15)
    assert r.status_code == 403


def test_delete_cascades(owner_tok, sales_ids):
    # separate route to avoid interfering with fixture teardown
    payload = {
        "name": f"TEST_del_{uuid.uuid4().hex[:6]}",
        "assigned_user_id": sales_ids["s1"],
        "stops": [{"latitude": 1, "longitude": 1, "sort": 0}],
    }
    c = requests.post(f"{API}/routes", headers=_h(owner_tok), json=payload, timeout=15)
    assert c.status_code == 201
    rid = c.json()["id"]

    d = requests.delete(f"{API}/routes/{rid}", headers=_h(owner_tok), timeout=15)
    assert d.status_code == 204

    g = requests.get(f"{API}/routes/{rid}", headers=_h(owner_tok), timeout=15)
    assert g.status_code == 404


# ---------- Property enrichment ----------

def test_property_address_enrichment(owner_tok, sales_ids):
    # Find a property with lat/lng
    props = requests.get(f"{API}/properties?limit=5", headers=_h(owner_tok), timeout=15)
    if props.status_code != 200:
        pytest.skip(f"properties list not available: {props.status_code}")
    body = props.json()
    items = body.get("items") if isinstance(body, dict) else body
    if not items:
        pytest.skip("no properties seeded")
    p = items[0]
    payload = {
        "name": f"TEST_enrich_{uuid.uuid4().hex[:6]}",
        "assigned_user_id": sales_ids["s1"],
        "stops": [{"property_id": p["id"], "sort": 0}],
    }
    c = requests.post(f"{API}/routes", headers=_h(owner_tok), json=payload, timeout=15)
    assert c.status_code == 201, c.text
    try:
        stop = c.json()["stops"][0]
        # address should be enriched from property when supplied
        assert stop["address"] == p.get("formatted_address", stop["address"])
        assert stop["property_id"] == p["id"]
    finally:
        requests.delete(f"{API}/routes/{c.json()['id']}", headers=_h(owner_tok), timeout=15)
