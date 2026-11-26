"""Iteration 137: Won/Lost auto-cancels open sales follow-ups (Office, Field, proposal acceptance), reopen, offline/conflicts."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
REP_A = ("sales_bk@example.com", "SalesBk#2026")
REP_B = ("sales1_38f545f9@example.com", "Sales1#2026")
NOW = datetime.now(timezone.utc)


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def owner():
    return _login(*OWNER)


@pytest.fixture(scope="module")
def rep_a():
    return _login(*REP_A)


@pytest.fixture(scope="module")
def rep_b():
    return _login(*REP_B)


def _iso(d):
    return d.isoformat()


def _lead(owner, rep):
    r = requests.post(f"{API}/properties", json={"address_line1": f"{uuid.uuid4().hex[:6]} TEST_Close Way", "city": "Austin", "state": "TX",
                                                 "zip_code": "78701", "latitude": 30.27, "longitude": -97.74}, headers=owner, timeout=20)
    lead = requests.post(f"{API}/properties/{r.json()['id']}/convert-to-lead", json={"name": f"TEST_Close {uuid.uuid4().hex[:6]}"}, headers=owner, timeout=20).json()
    me = requests.get(f"{API}/auth/me", headers=rep, timeout=20).json()["id"]
    assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": me}, headers=owner, timeout=20).status_code == 200
    return lead


def _fu(h, lid, **b):
    r = requests.post(f"{API}/leads/{lid}/follow-ups", json=b, headers=h, timeout=20)
    assert r.status_code == 201, r.text
    return r.json()


def _fus(h, lid):
    return {f["id"]: f for f in requests.get(f"{API}/leads/{lid}/follow-ups", headers=h, timeout=20).json()}


def _audit(owner, lid, action):
    r = requests.get(f"{API}/audit", params={"action": action, "limit": 200}, headers=owner, timeout=20)
    assert r.status_code == 200, r.text
    return [x for x in r.json()["items"] if str(x.get("entity_id")) == lid]


def _setup_history(rep, lid):
    open1 = _fu(rep, lid, kind="call", note="TEST open 1", due_at=_iso(NOW - timedelta(days=1)))
    open2 = _fu(rep, lid, kind="text", note="TEST open 2", due_at=_iso(NOW + timedelta(days=2)))
    done = _fu(rep, lid, kind="call", note="TEST already done", status="done")
    canc = _fu(rep, lid, kind="call", note="TEST already cancelled", due_at=_iso(NOW + timedelta(days=1)))
    assert requests.patch(f"{API}/follow-ups/{canc['id']}", json={"status": "cancelled", "outcome": "rep cancelled"}, headers=rep, timeout=20).status_code == 200
    return open1, open2, done, canc


def test_office_won_cancels_open_follow_ups_and_preserves_history(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    o1, o2, done, canc = _setup_history(rep_a, lid)
    before = _fus(owner, lid)
    md = requests.get(f"{API}/mobile/my-day", headers=rep_a, timeout=30).json()
    assert o1["id"] in [i["id"] for i in md["follow_ups"]["items"]]
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "won"}, headers=owner, timeout=20).status_code == 200
    after = _fus(owner, lid)
    assert set(after) == set(before)  # nothing deleted
    for f in (o1, o2):
        assert after[f["id"]]["status"] == "cancelled" and after[f["id"]]["outcome"] == "Lead marked Won"
    assert after[done["id"]]["status"] == "done" and after[done["id"]]["completed_at"] == before[done["id"]]["completed_at"]
    assert after[canc["id"]]["outcome"] == "rep cancelled" and after[canc["id"]]["completed_at"] == before[canc["id"]]["completed_at"]
    logs = _audit(owner, lid, "followup.auto_cancel")
    assert len(logs) == 1 and logs[0]["detail"]["reason"] == "Lead marked Won" and set(logs[0]["detail"]["follow_up_ids"]) == {o1["id"], o2["id"]}
    # Home / My Day / next action
    for path, h in (("/mobile/my-day", rep_a), ("/dashboard/attention", rep_a), ("/dashboard/attention", owner)):
        d = requests.get(f"{API}{path}", headers=h, timeout=30).json()
        assert not any(i.get("lead_id") == lid for k in ("follow_ups", "no_follow_up") for i in d[k]["items"])
    row = next(l for l in requests.get(f"{API}/leads", headers=rep_a, timeout=30).json() if l["id"] == lid)
    assert row["open_follow_ups"] == 0 and row["next_action"]["type"] == "stage"
    field = requests.get(f"{API}/mobile/leads/{lid}", headers=rep_a, timeout=20).json()
    assert field["next_action"]["text"] == row["next_action"]["text"]
    assert all(f["status"] != "open" for f in field["follow_ups"])
    # setting Won again is not a transition: no second audit entry
    requests.patch(f"{API}/leads/{lid}", json={"status": "won"}, headers=owner, timeout=20)
    assert len(_audit(owner, lid, "followup.auto_cancel")) == 1

    # reopen: nothing restored; new follow-ups allowed and open
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "contacted"}, headers=rep_a, timeout=20).status_code == 200
    assert all(_fus(owner, lid)[f["id"]]["status"] == "cancelled" for f in (o1, o2))
    new = _fu(rep_a, lid, kind="call", note="TEST after reopen", due_at=_iso(NOW + timedelta(hours=2)))
    assert new["status"] == "open"
    row = next(l for l in requests.get(f"{API}/leads", headers=rep_a, timeout=30).json() if l["id"] == lid)
    assert row["open_follow_ups"] == 1 and "TEST after reopen" in row["next_action"]["text"]


def test_field_lost_cancels_and_offline_changes_cannot_reopen(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    o1 = _fu(rep_a, lid, kind="call", note="TEST pending done", due_at=_iso(NOW))
    o2 = _fu(rep_a, lid, kind="call", note="TEST pending cancel", due_at=_iso(NOW))
    o3 = _fu(rep_a, lid, kind="call", note="TEST reopen attempt", due_at=_iso(NOW))
    tok = {f["id"]: f["if_match"] for f in (o1, o2, o3)}
    # Field marks the lead Lost
    det = requests.get(f"{API}/mobile/leads/{lid}", headers=rep_a, timeout=20).json()
    r = requests.patch(f"{API}/mobile/leads/{lid}", json={"status": "lost"}, headers={**rep_a, "If-Match": det["if_match"]}, timeout=20)
    assert r.status_code == 200, r.text
    f = _fus(owner, lid)
    assert all(f[x["id"]]["status"] == "cancelled" and f[x["id"]]["outcome"] == "Lead marked Lost" for x in (o1, o2, o3))
    assert _audit(owner, lid, "followup.auto_cancel")[0]["detail"]["reason"] == "Lead marked Lost"
    # queued offline changes replayed after the auto-cancel
    c = requests.patch(f"{API}/follow-ups/{o1['id']}", json={"status": "done", "lead_id": lid}, headers={**rep_a, "If-Match": tok[o1["id"]]}, timeout=20)
    assert c.status_code == 409 and c.json()["detail"]["server"]["status"] == "cancelled" and "Lead marked Lost" in c.json()["detail"]["message"]
    assert requests.patch(f"{API}/follow-ups/{o2['id']}", json={"status": "cancelled"}, headers=rep_a, timeout=20).status_code == 200  # no-op
    assert _fus(owner, lid)[o2["id"]]["outcome"] == "Lead marked Lost"
    for body in ({"status": "open"}, {"due_at": _iso(NOW + timedelta(days=1))}, {"note": "x"}):
        assert requests.patch(f"{API}/follow-ups/{o3['id']}", json=body, headers=rep_a, timeout=20).status_code == 409
    # an offline-created follow-up arriving after the lead was closed is kept, but not outstanding
    late = _fu(rep_a, lid, id=str(uuid.uuid4()), kind="call", note="TEST late offline create", due_at=_iso(NOW), lead_id=lid)
    assert late["status"] == "cancelled" and late["outcome"] == "Lead marked Lost"
    # logging a contact on a closed lead is still allowed (history)
    assert _fu(rep_a, lid, kind="call", status="done", note="TEST post-loss call")["status"] == "done"
    assert all(v["status"] != "open" for v in _fus(owner, lid).values())


def test_proposal_acceptance_cancels_follow_ups_but_not_jobs(owner, rep_a, rep_b):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    o1 = _fu(rep_a, lid, kind="call", note="TEST before accept", due_at=_iso(NOW + timedelta(days=1)))
    assert requests.post(f"{API}/customers/from-lead/{lid}", headers=owner, timeout=20).status_code in (200, 201)
    cust = requests.get(f"{API}/leads/{lid}", headers=owner, timeout=20).json()["customer_id"]
    est = requests.post(f"{API}/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0,
                                                  "items": [{"description": "TEST roof", "quantity": 1, "selling_unit_price": 100}]}, headers=owner, timeout=20).json()
    q = requests.post(f"{API}/quotes", json={"estimate_id": est["id"]}, headers=owner, timeout=20).json()
    acc = requests.post(f"{API}/quotes/{q['id']}/accept", json={"acceptance_name": "TEST Buyer"}, headers=owner, timeout=30)
    assert acc.status_code == 200, acc.text
    job_id = acc.json()["job_id"]
    assert requests.get(f"{API}/leads/{lid}", headers=owner, timeout=20).json()["status"] == "won"
    f = _fus(owner, lid)[o1["id"]]
    assert f["status"] == "cancelled" and f["outcome"] == "Lead marked Won"
    job = requests.get(f"{API}/jobs/{job_id}", headers=owner, timeout=20)
    assert job.status_code == 200 and job.json()["status"] == "created"
    # schedule the job, then mark the lead Lost: production is untouched
    start = (NOW + timedelta(days=10)).date().isoformat()
    assert requests.patch(f"{API}/jobs/{job_id}", json={"scheduled_start": start, "scheduled_end": start}, headers=owner, timeout=20).status_code == 200
    before = requests.get(f"{API}/jobs/{job_id}", headers=owner, timeout=20).json()
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "lost"}, headers=owner, timeout=20).status_code == 200
    after = requests.get(f"{API}/jobs/{job_id}", headers=owner, timeout=20).json()
    for k in ("status", "scheduled_start", "scheduled_end", "assigned_user_id", "crew_id"):
        assert after.get(k) == before.get(k), k
    # permissions: another rep can't close or reopen this lead or touch its follow-ups
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "won"}, headers=rep_b, timeout=20).status_code == 403
    assert requests.patch(f"{API}/mobile/leads/{lid}", json={"status": "won"}, headers=rep_b, timeout=20).status_code == 403
    assert requests.get(f"{API}/leads/{lid}/follow-ups", headers=rep_b, timeout=20).status_code == 403
