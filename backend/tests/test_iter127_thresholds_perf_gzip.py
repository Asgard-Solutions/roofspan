"""Iter127: threshold rules (incl. RP0 job shortage), quick-count agreement, list/PO perf + gzip, downloads through gzip, PO receive."""
import os, time, uuid, pytest, requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
EXCL = {"completed", "cancelled", "closed", "archived", "lost"}


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=OWNER)
    if r.status_code != 200:
        pytest.skip("login failed")
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


def _mk(owner, on_hand, rp):
    name = f"TEST_I127_{uuid.uuid4().hex[:8]}"
    r = owner.post(f"{BASE_URL}/api/materials", json={"name": name, "unit": "EA", "quantity_on_hand": on_hand, "reorder_threshold": rp})
    assert r.status_code == 201, r.text
    return r.json()["id"], name


def _cleanup(owner, mid):
    owner.patch(f"{BASE_URL}/api/materials/{mid}", json={"active": False})
    owner.delete(f"{BASE_URL}/api/materials/{mid}")


# Threshold rule (e): RP 0 + active job plan with no stock -> short_for_jobs + needs_ordering; job-detail low_stock False
def test_rp0_job_shortage(owner):
    jobs = [j for j in owner.get(f"{BASE_URL}/api/jobs", timeout=60).json() if j["status"] not in EXCL]
    if not jobs:
        pytest.skip("no active job")
    job = jobs[0]
    mid, name = _mk(owner, 0, 0)
    jm = None
    try:
        r = owner.post(f"{BASE_URL}/api/jobs/{job['id']}/materials", json={"material_id": mid, "planned_quantity": 7})
        assert r.status_code == 201, r.text
        jm = r.json()
        assert jm["low_stock"] is False  # RP 0 never Low
        qc = owner.get(f"{BASE_URL}/api/materials/quick-counts").json()
        assert mid in qc["short_for_jobs_ids"] and mid in qc["needs_ordering_ids"]
        row = next(m for m in owner.get(f"{BASE_URL}/api/materials", params={"q": name}).json() if m["id"] == mid)
        assert row["low_stock"] is False and row["required"] == 7 and row["projected"] == -7
        sugg = [x["material_id"] for x in owner.get(f"{BASE_URL}/api/inventory/reorder-suggestions").json()["suggestions"]]
        assert mid not in sugg  # RP 0 -> no reorder suggestion; flagged only via short_for_jobs
        lows = [m["id"] for m in owner.get(f"{BASE_URL}/api/materials", params={"low_stock": True, "q": name}).json()]
        assert mid not in lows
    finally:
        if jm:
            owner.delete(f"{BASE_URL}/api/jobs/{job['id']}/materials/{jm['id']}")
        _cleanup(owner, mid)


# Low-stock filter globally only returns RP>0 && available<=RP; dashboard Low Stock count matches
def test_low_stock_filter_global_and_dashboard(owner):
    allm = owner.get(f"{BASE_URL}/api/materials", timeout=60).json()
    lows = owner.get(f"{BASE_URL}/api/materials", params={"low_stock": True}, timeout=60).json()
    exp = {m["id"] for m in allm if (m["reorder_threshold"] or 0) > 0 and m["available"] <= m["reorder_threshold"]}
    assert {m["id"] for m in lows} == exp
    assert all(m["low_stock"] == (m["id"] in exp) for m in allm)
    active_low = len({m["id"] for m in allm if m["active"] and m["id"] in exp})
    d = owner.get(f"{BASE_URL}/api/dashboard/purchasing", timeout=60)
    if d.status_code == 200:
        body = d.json()
        lv = body.get("low_stock") if "low_stock" in body else body.get("low_stock_count")
        print("dashboard low", lv, "expected", active_low)
        if lv is not None:
            assert lv == active_low


# Quick counts == filtered rows; needs_ordering == short ∪ (RP>0 && projected<=RP) over active rows
def _quick_snapshot(owner):
    qc = owner.get(f"{BASE_URL}/api/materials/quick-counts").json()
    lists = {k: len(owner.get(f"{BASE_URL}/api/materials", params={"quick": k, "active": True}, timeout=60).json()) for k in qc["counts"]}
    allm = owner.get(f"{BASE_URL}/api/materials", params={"active": True}, timeout=60).json()
    after = owner.get(f"{BASE_URL}/api/materials/quick-counts").json()
    return qc, lists, allm, after == qc


def test_quick_counts_agree(owner):
    # Other suites create/adjust materials concurrently, so compare only a snapshot whose quick-counts were
    # identical before and after the list reads (no materials changed in between).
    for _ in range(5):
        qc, lists, allm, stable = _quick_snapshot(owner)
        if stable:
            break
    else:
        pytest.skip("materials kept changing under concurrent suites; no stable snapshot")
    for k, v in qc["counts"].items():
        assert lists[k] == v, k
    reorder = {m["id"] for m in allm if (m["reorder_threshold"] or 0) > 0 and m["projected"] <= m["reorder_threshold"]}
    assert set(qc["needs_ordering_ids"]) == reorder | set(qc["short_for_jobs_ids"])


# Performance + gzip for big lists
@pytest.mark.parametrize("path,limit", [("/api/materials", 2.5), ("/api/purchase-orders", 3.0)])
def test_perf_gzip(owner, path, limit):
    t = time.time()
    r = owner.get(f"{BASE_URL}{path}", headers={"Accept-Encoding": "gzip"}, timeout=60)
    dt = time.time() - t
    assert r.status_code == 200
    print(path, f"{dt:.2f}s", r.headers.get("content-encoding"), r.headers.get("content-length"), len(r.content), len(r.json()))
    assert r.headers.get("content-encoding") == "gzip"
    assert dt < limit


def test_po_filters_and_receive(owner):
    for st in ("ordered", "received", "cancelled"):
        rows = owner.get(f"{BASE_URL}/api/purchase-orders", params={"status": st}, timeout=60).json()
        assert all(p["status"] == st for p in rows)
    mid, name = _mk(owner, 0, 0)
    try:
        sup = owner.get(f"{BASE_URL}/api/suppliers").json()
        po = owner.post(f"{BASE_URL}/api/purchase-orders", json={"supplier_id": sup[0]["id"] if sup else None,
                        "supplier_name": None if sup else "TEST_Sup", "notes": "TEST_I127",
                        "items": [{"material_id": mid, "description": name, "quantity": 8, "unit_cost": 1}]}).json()
        owner.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/status", json={"status": "ordered"})
        r = owner.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/receive", json={"items": [{"po_item_id": po["items"][0]["id"], "quantity": 3}]})
        assert r.status_code == 200, r.text
        g = owner.get(f"{BASE_URL}/api/purchase-orders/{po['id']}").json()
        assert g["items"][0]["received_quantity"] == 3
        row = next(m for m in owner.get(f"{BASE_URL}/api/materials", params={"q": name}).json() if m["id"] == mid)
        assert row["on_hand"] == 3 and row["on_order"] == 5
        owner.post(f"{BASE_URL}/api/purchase-orders/{po['id']}/status", json={"status": "cancelled"})
    finally:
        _cleanup(owner, mid)


# Binary downloads through gzip still valid
def test_downloads_through_gzip(owner):
    quotes = owner.get(f"{BASE_URL}/api/quotes", timeout=60).json()
    qs = quotes if isinstance(quotes, list) else quotes.get("items", [])
    ok = 0
    for q in qs[:15]:
        r = owner.get(f"{BASE_URL}/api/quotes/{q['id']}/proposal.pdf", headers={"Accept-Encoding": "gzip"}, timeout=90)
        if r.status_code == 200:
            assert r.content[:4] == b"%PDF", r.content[:20]
            print("proposal pdf", q["id"], r.headers.get("content-encoding"), len(r.content))
            ok += 1
            s = owner.get(f"{BASE_URL}/api/quotes/{q['id']}/site-plan.pdf", headers={"Accept-Encoding": "gzip"}, timeout=90)
            print("site plan", s.status_code, s.headers.get("content-type"), s.content[:4])
            if s.status_code == 200:
                assert s.content[:4] == b"%PDF"
            break
    assert ok, "no proposal pdf downloadable"
    c = owner.get(f"{BASE_URL}/api/reports/costing/profitability.csv", headers={"Accept-Encoding": "gzip"}, timeout=90)
    print("csv", c.status_code, c.headers.get("content-encoding"), c.text[:80])
    assert c.status_code == 200 and "," in c.text
