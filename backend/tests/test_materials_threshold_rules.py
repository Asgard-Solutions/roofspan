"""Reorder-point rules (June 2026): 0 = no threshold; Low = Available <= RP; Needs ordering = Projected <= RP (or job short)."""
import os, uuid, pytest, requests
from services.inventory_core import is_low_stock, reorder_point_reached

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


def test_rule_functions():
    assert not is_low_stock(0, 0) and not reorder_point_reached(0, 0)
    assert not is_low_stock(-5, 0) and not reorder_point_reached(-5, None)
    assert is_low_stock(10, 10) and reorder_point_reached(10, 10)
    assert is_low_stock(5, 10) and reorder_point_reached(5, 10)
    assert not is_low_stock(11, 10) and not reorder_point_reached(11, 10)


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"})
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.mark.parametrize("on_hand,rp,low", [(0, 0, False), (10, 10, True), (11, 10, False), (5, 10, True)])
def test_api_low_and_needs_ordering_agree(owner, on_hand, rp, low):
    r = owner.post(f"{BASE_URL}/api/materials", json={"name": f"TEST_RP_{uuid.uuid4().hex[:8]}", "unit": "EA",
                                                      "quantity_on_hand": on_hand, "reorder_threshold": rp})
    assert r.status_code in (200, 201), r.text
    mid = r.json()["id"]
    try:
        row = next(m for m in owner.get(f"{BASE_URL}/api/materials", params={"q": r.json()["name"]}).json() if m["id"] == mid)
        assert row["low_stock"] is low
        qc = owner.get(f"{BASE_URL}/api/materials/quick-counts").json()
        assert (mid in qc["needs_ordering_ids"]) is low  # no jobs/POs: projected == on hand == available
        assert mid not in qc["short_for_jobs_ids"]
        sugg = [x["material_id"] for x in owner.get(f"{BASE_URL}/api/inventory/reorder-suggestions").json()["suggestions"]]
        assert (mid in sugg) is low
        lows = [m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"low_stock": True, "q": r.json()["name"]}).json()]
        assert (mid in lows) is low
    finally:
        owner.delete(f"{BASE_URL}/api/materials/{mid}")
