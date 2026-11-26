"""Iteration 135: Office <-> Field follow-up sync, offline replay/conflicts, reassignment, permissions, time zones/DST."""
import os
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests

from services.follow_ups import day_bounds, _when

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
REP_A = ("sales_bk@example.com", "SalesBk#2026")
REP_B = ("sales1_38f545f9@example.com", "Sales1#2026")


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


def _me(h):
    return requests.get(f"{API}/auth/me", headers=h, timeout=20).json()["id"]


def _lead(owner, assignee_headers):
    r = requests.post(f"{API}/properties", json={"address_line1": f"{uuid.uuid4().hex[:6]} TEST_Sync Way", "city": "Austin", "state": "TX",
                                                 "zip_code": "78701", "latitude": 30.27, "longitude": -97.74}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    r = requests.post(f"{API}/properties/{r.json()['id']}/convert-to-lead", json={"name": f"TEST_Sync {uuid.uuid4().hex[:6]}"}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    lead = r.json()
    assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": _me(assignee_headers)}, headers=owner, timeout=20).status_code == 200
    return lead


def _iso(d):
    return d.astimezone(timezone.utc).isoformat()


def _fu(h, lid, **b):
    return requests.post(f"{API}/leads/{lid}/follow-ups", json=b, headers=h, timeout=20)


def _patch(h, fid, body, if_match=None):
    hh = {**h, **({"If-Match": if_match} if if_match else {})}
    return requests.patch(f"{API}/follow-ups/{fid}", json=body, headers=hh, timeout=20)


def _field_detail(h, lid):
    return requests.get(f"{API}/mobile/leads/{lid}", headers=h, timeout=20)


def _next_actions(h, lid, tz="UTC"):
    office_detail = requests.get(f"{API}/leads/{lid}/workflow", params={"tz": tz}, headers=h, timeout=20).json()["next_action"]
    office_list = next(l for l in requests.get(f"{API}/leads", params={"tz": tz}, headers=h, timeout=30).json() if l["id"] == lid)["next_action"]
    field_list = next(l for l in requests.get(f"{API}/mobile/leads", params={"tz": tz}, headers=h, timeout=30).json() if l["id"] == lid)["next_action"]
    field_detail = _field_detail(h, lid).json()["next_action"]
    return office_detail, office_list, field_list, field_detail


# ---------- 1. Office <-> Field sync ----------
def test_office_and_field_see_the_same_follow_ups_both_ways(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    now = datetime.now(timezone.utc)
    office = _fu(owner, lid, kind="call", note="TEST from office", due_at=_iso(now + timedelta(days=2))).json()
    field = _fu(rep_a, lid, id=str(uuid.uuid4()), kind="text", note="TEST from field", due_at=_iso(now + timedelta(days=1)), lead_id=lid).json()
    fd = _field_detail(rep_a, lid).json()
    assert {office["id"], field["id"]} <= {f["id"] for f in fd["follow_ups"] if f["status"] == "open"}
    od = requests.get(f"{API}/leads/{lid}/follow-ups", headers=owner, timeout=20).json()
    assert {office["id"], field["id"]} <= {f["id"] for f in od if f["status"] == "open"}

    # complete in Field -> Office sees done; the other stays open (independent)
    assert _patch(rep_a, field["id"], {"status": "done", "lead_id": lid}, field["if_match"]).status_code == 200
    od = {f["id"]: f for f in requests.get(f"{API}/leads/{lid}/follow-ups", headers=owner, timeout=20).json()}
    assert od[field["id"]]["status"] == "done" and od[office["id"]]["status"] == "open"
    # reschedule in Office -> Field sees new date
    new_due = _iso(now + timedelta(days=4))
    r = _patch(owner, office["id"], {"due_at": new_due}, office["if_match"])
    assert r.status_code == 200
    fd = {f["id"]: f for f in _field_detail(rep_a, lid).json()["follow_ups"]}
    assert datetime.fromisoformat(fd[office["id"]]["due_at"]) == datetime.fromisoformat(new_due)
    # cancel in Office -> Field sees cancelled, never open again
    assert _patch(owner, office["id"], {"status": "cancelled"}).status_code == 200
    fd = {f["id"]: f for f in _field_detail(rep_a, lid).json()["follow_ups"]}
    assert fd[office["id"]]["status"] == "cancelled" and fd[field["id"]]["status"] == "done"
    assert not any(i["lead_id"] == lid for i in requests.get(f"{API}/mobile/my-day", headers=rep_a, timeout=30).json()["follow_ups"]["items"])


def test_same_next_action_everywhere(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    for h in (rep_a, owner):
        acts = _next_actions(h, lid)
        assert len({a["text"] for a in acts}) == 1 and acts[0]["type"] == "stage", acts
    assert _next_actions(rep_a, lid)[0]["text"] == "Create the customer record to start the sale."
    when = datetime.now(timezone.utc) + timedelta(days=1)
    r = requests.post(f"{API}/inspections", json={"lead_id": lid, "status": "scheduled", "inspection_date": _iso(when)}, headers=owner, timeout=20)
    assert r.status_code == 201
    acts = _next_actions(rep_a, lid)
    assert {a["text"] for a in acts} == {"Inspection booked"} and {a["type"] for a in acts} == {"inspection"}
    f = _fu(rep_a, lid, kind="call", note="TEST confirm time", due_at=_iso(when - timedelta(hours=3))).json()
    acts = _next_actions(rep_a, lid)
    assert {a["text"] for a in acts} == {"Call: TEST confirm time"}
    assert acts[0]["fallback"]["text"] == "Inspection booked"  # what Field shows offline after completing it
    _patch(rep_a, f["id"], {"status": "done"})
    assert {a["text"] for a in _next_actions(rep_a, lid)} == {"Inspection booked"}
    # a Won lead with a leftover open follow-up: every surface shows stage guidance, not an overdue reminder
    _fu(rep_a, lid, kind="call", note="TEST leftover", due_at=_iso(when - timedelta(days=5)))
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "won"}, headers=owner, timeout=20).status_code == 200
    acts = _next_actions(rep_a, lid)
    assert len({a["text"] for a in acts}) == 1 and {a["type"] for a in acts} <= {"stage", "inspection"} and "TEST leftover" not in acts[0]["text"]


def test_door_visit_in_office_history_once(owner, rep_a):
    lead = _lead(owner, rep_a)
    key = str(uuid.uuid4())
    body = {"property_id": lead["property_id"], "outcome": "callback", "notes": "TEST come back friday"}
    for _ in range(2):  # interrupted sync retried with the same idempotency key
        r = requests.post(f"{API}/mobile/visits", json=body, headers={**rep_a, "Idempotency-Key": key}, timeout=20)
        assert r.status_code in (200, 201), r.text
    visits = requests.get(f"{API}/leads/{lead['id']}", headers=owner, timeout=20).json()["visits"]
    assert len([v for v in visits if v["notes"] == "TEST come back friday"]) == 1


def test_booked_inspection_sync(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    key = str(uuid.uuid4())
    body = {"lead_id": lid, "property_id": lead["property_id"], "status": "scheduled", "inspection_date": _iso(datetime.now(timezone.utc) + timedelta(days=2))}
    ids = {requests.post(f"{API}/mobile/inspections", json=body, headers={**rep_a, "Idempotency-Key": key}, timeout=20).json()["id"] for _ in range(2)}
    assert len(ids) == 1
    iid = ids.pop()
    office = requests.get(f"{API}/inspections", params={"lead_id": lid}, headers=owner, timeout=20).json()
    assert [i["status"] for i in office if i["id"] == iid] == ["scheduled"]
    assert requests.patch(f"{API}/inspections/{iid}", json={"status": "cancelled"}, headers=owner, timeout=20).json()["status"] == "cancelled"
    assert not _field_detail(rep_a, lid).json()["scheduled_inspections"]
    r2 = requests.post(f"{API}/mobile/inspections", json={**body, "inspection_date": _iso(datetime.now(timezone.utc) + timedelta(days=3))}, headers=rep_a, timeout=20).json()
    tok = r2["if_match"]
    done = requests.patch(f"{API}/mobile/inspections/{r2['id']}", json={"findings": "TEST ok", "roof_condition": "Good"}, headers={**rep_a, "If-Match": tok}, timeout=20)
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert [i["status"] for i in requests.get(f"{API}/inspections", params={"lead_id": lid}, headers=owner, timeout=20).json() if i["id"] == r2["id"]] == ["completed"]


# ---------- 2. Offline replay & conflicts ----------
def test_offline_replay_and_conflicts(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    fid = str(uuid.uuid4())
    body = {"id": fid, "kind": "call", "due_at": _iso(datetime.now(timezone.utc)), "note": "TEST offline", "lead_id": lid}
    assert {_fu(rep_a, lid, **body).json()["id"] for _ in range(3)} == {fid}  # retried create: one record
    # offline complete queued after the (offline) create; both replayed twice
    for _ in range(2):
        assert _patch(rep_a, fid, {"status": "done", "lead_id": lid}).status_code == 200
    assert [f["status"] for f in requests.get(f"{API}/leads/{lid}/follow-ups", headers=owner, timeout=20).json() if f["id"] == fid] == ["done"]

    # Office reschedules while Field has a pending 'done' based on the old copy -> conflict, Office kept
    f2 = _fu(owner, lid, kind="call", due_at=_iso(datetime.now(timezone.utc) + timedelta(days=1))).json()
    assert _patch(owner, f2["id"], {"due_at": _iso(datetime.now(timezone.utc) + timedelta(days=3))}, f2["if_match"]).status_code == 200
    c = _patch(rep_a, f2["id"], {"status": "done", "lead_id": lid}, f2["if_match"])
    assert c.status_code == 409 and c.json()["detail"]["server"]["status"] == "open"
    # 'Apply mine' with the server's current token succeeds
    assert _patch(rep_a, f2["id"], {"status": "done"}, c.json()["detail"]["server"]["if_match"]).status_code == 200

    # Office cancels while Field has a pending 'done' -> conflict even without If-Match; never revived
    f3 = _fu(owner, lid, kind="call", due_at=_iso(datetime.now(timezone.utc) + timedelta(days=1))).json()
    assert _patch(owner, f3["id"], {"status": "cancelled"}).status_code == 200
    c = _patch(rep_a, f3["id"], {"status": "done", "lead_id": lid})
    assert c.status_code == 409 and c.json()["detail"]["server"]["status"] == "cancelled"
    assert _patch(rep_a, f3["id"], {"note": "TEST edit"}).status_code == 409
    assert _patch(owner, f3["id"], {"status": "cancelled"}).status_code == 200  # repeat cancel = no-op
    final = {f["id"]: f["status"] for f in requests.get(f"{API}/leads/{lid}/follow-ups", headers=owner, timeout=20).json()}
    assert final[f3["id"]] == "cancelled" and final[fid] == "done" and final[f2["id"]] == "done"


# ---------- 4. Permissions + reassignment ----------
def test_permissions_and_reassignment(owner, rep_a, rep_b):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    f = _fu(rep_a, lid, kind="call", note="TEST reassign", due_at=_iso(datetime.now(timezone.utc) - timedelta(hours=1))).json()
    insp = requests.post(f"{API}/inspections", json={"lead_id": lid, "status": "scheduled", "inspection_date": _iso(datetime.now(timezone.utc) + timedelta(days=1))}, headers=rep_a, timeout=20).json()
    md = requests.get(f"{API}/mobile/my-day", headers=rep_a, timeout=30).json()
    assert f["id"] in [i["id"] for i in md["follow_ups"]["items"]] and insp["id"] in [i["id"] for i in md["inspections"]["items"]]
    # rep B can't touch rep A's lead
    for r in (requests.get(f"{API}/leads/{lid}/follow-ups", headers=rep_b, timeout=20), _fu(rep_b, lid, due_at=_iso(datetime.now(timezone.utc))),
              _patch(rep_b, f["id"], {"status": "done"}), _field_detail(rep_b, lid), requests.get(f"{API}/leads/{lid}", headers=rep_b, timeout=20),
              requests.get(f"{API}/inspections", params={"lead_id": lid}, headers=rep_b, timeout=20),
              requests.patch(f"{API}/inspections/{insp['id']}", json={"status": "cancelled"}, headers=rep_b, timeout=20),
              requests.post(f"{API}/inspections", json={"lead_id": lid, "status": "scheduled", "inspection_date": _iso(datetime.now(timezone.utc))}, headers=rep_b, timeout=20)):
        assert r.status_code == 403, (r.request.method, r.request.url, r.status_code)
    assert not any(i["lead_id"] == lid for i in requests.get(f"{API}/mobile/my-day", headers=rep_b, timeout=30).json()["follow_ups"]["items"])
    # reassign A -> B
    assert requests.put(f"{API}/leads/{lid}/assign", json={"user_id": _me(rep_b)}, headers=owner, timeout=20).status_code == 200
    for r in (requests.get(f"{API}/leads/{lid}/follow-ups", headers=rep_a, timeout=20), _field_detail(rep_a, lid), _patch(rep_a, f["id"], {"status": "done"})):
        assert r.status_code == 403
    for path in ("/mobile/my-day", "/dashboard/attention"):
        d = requests.get(f"{API}{path}", headers=rep_a, timeout=30).json()
        assert not any(i.get("lead_id") == lid for k in ("follow_ups", "inspections", "proposals", "no_follow_up") for i in d[k]["items"])
    assert lid not in [l["id"] for l in requests.get(f"{API}/mobile/leads", headers=rep_a, timeout=30).json()]
    md = requests.get(f"{API}/mobile/my-day", headers=rep_b, timeout=30).json()
    assert f["id"] in [i["id"] for i in md["follow_ups"]["items"]]  # the follow-up moved with the lead
    assert _patch(rep_b, f["id"], {"status": "done"}).status_code == 200


# ---------- 5. Dates, time zones, DST ----------
def test_day_bounds_dst_and_midnight():
    chi = "America/Chicago"
    # spring forward (23h day) and fall back (25h day)
    s, e = day_bounds(chi, datetime(2026, 3, 8, 18, 0, tzinfo=timezone.utc))
    assert (e - s) == timedelta(hours=23) and s.astimezone(ZoneInfo(chi)).hour == 0 and e.astimezone(ZoneInfo(chi)).hour == 0
    s, e = day_bounds(chi, datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc))
    assert (e - s) == timedelta(hours=25) and e.astimezone(ZoneInfo(chi)).day == 2
    # a follow-up at 23:30 local on the DST day is still 'today'; 00:00 next day is 'upcoming'
    due = datetime(2026, 11, 1, 23, 30, tzinfo=ZoneInfo(chi))
    assert _when(due, s, e) == "today"
    assert _when(datetime(2026, 11, 2, 0, 0, tzinfo=ZoneInfo(chi)), s, e) == "upcoming"
    # midnight: one minute before local midnight vs at it, seen just after midnight
    s, e = day_bounds(chi, datetime(2026, 6, 11, 5, 1, tzinfo=timezone.utc))  # 00:01 CDT on Jun 11
    assert _when(datetime(2026, 6, 10, 23, 59, tzinfo=ZoneInfo(chi)), s, e) == "overdue"
    assert _when(datetime(2026, 6, 11, 0, 0, tzinfo=ZoneInfo(chi)), s, e) == "today"
    # two devices in different zones: same instant, each classified by its own local day
    inst = datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc)  # Jun 10 22:00 Chicago, Jun 11 13:00 Sydney
    now = datetime(2026, 6, 11, 4, 0, tzinfo=timezone.utc)
    assert _when(inst, *day_bounds(chi, now)) == "today"
    assert _when(inst, *day_bounds("Australia/Sydney", now)) == "today"
    assert _when(inst, *day_bounds("Asia/Tokyo", datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc))) == "overdue"  # Jun 12 01:00 Tokyo
    assert day_bounds("Not/AZone", now) == day_bounds("UTC", now)  # bad tz falls back to UTC, no error


def test_api_classifies_by_callers_time_zone(owner, rep_a):
    lead = _lead(owner, rep_a)
    lid = lead["id"]
    now = datetime.now(timezone.utc)
    # just before the start of 'today' in Kiritimati (UTC+14) -> overdue there; API must match each caller zone's own day
    k_start, _ = day_bounds("Pacific/Kiritimati", now)
    due = k_start - timedelta(minutes=1)
    f = _fu(rep_a, lid, kind="call", note="TEST tz", due_at=_iso(due)).json()
    assert datetime.fromisoformat(f["due_at"]) == due  # stored instant never shifts
    exp = {}
    for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago", "America/Chicago", "Asia/Kolkata"):
        exp[tz] = _when(due, *day_bounds(tz, datetime.now(timezone.utc)))
        row = next(l for l in requests.get(f"{API}/leads", params={"tz": tz}, headers=rep_a, timeout=30).json() if l["id"] == lid)
        assert row["next_action"]["when"] == exp[tz], tz
        items = requests.get(f"{API}/mobile/my-day", params={"tz": tz}, headers=rep_a, timeout=30).json()["follow_ups"]["items"]
        hit = [i for i in items if i["id"] == f["id"]]
        assert (hit[0]["when"] if hit else "upcoming") == exp[tz], tz
    assert exp["Pacific/Kiritimati"] == "overdue"
    # naive datetimes from a client are treated as UTC, not server-local
    naive = (now + timedelta(days=1)).replace(tzinfo=None, microsecond=0)
    g = _fu(rep_a, lid, kind="call", due_at=naive.isoformat()).json()
    assert datetime.fromisoformat(g["due_at"]) == naive.replace(tzinfo=timezone.utc)
