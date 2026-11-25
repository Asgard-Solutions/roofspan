"""Iteration 133: sales follow-ups, reminders, scheduled inspections, shared lead statuses (Office + Field)."""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from sqlalchemy import text

from tests._test_data_cleanup import _session

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
SALES_BK = ("sales_bk@example.com", "SalesBk#2026")
TZ = "America/Chicago"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _sql(stmt, **kw):
    async def run():
        eng, S = _session()
        try:
            async with S() as s:
                await s.execute(text(stmt), kw)
                await s.commit()
        finally:
            await eng.dispose()
    asyncio.run(run())


@pytest.fixture(scope="module")
def owner():
    return _login(*OWNER)


@pytest.fixture(scope="module")
def sales():
    return _login(*SALES_BK)


@pytest.fixture(scope="module")
def sales_id(sales):
    return requests.get(f"{API}/auth/me", headers=sales, timeout=20).json()["id"]


def _new_lead(owner, name):
    r = requests.post(f"{API}/properties", json={"address_line1": f"{uuid.uuid4().hex[:6]} TEST_FollowUp Way", "city": "Austin", "state": "TX",
                                                 "zip_code": "78701", "latitude": 30.27, "longitude": -97.74}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    r = requests.post(f"{API}/properties/{r.json()['id']}/convert-to-lead", json={"name": name}, headers=owner, timeout=20)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture(scope="module")
def my_lead(owner, sales_id):
    lead = _new_lead(owner, f"TEST_FU Mine {uuid.uuid4().hex[:6]}")
    assert requests.put(f"{API}/leads/{lead['id']}/assign", json={"user_id": sales_id}, headers=owner, timeout=20).status_code == 200
    return lead


@pytest.fixture(scope="module")
def other_lead(owner):
    return _new_lead(owner, f"TEST_FU Other {uuid.uuid4().hex[:6]}")


def _fu(h, lead_id, **body):
    return requests.post(f"{API}/leads/{lead_id}/follow-ups", json=body, headers=h, timeout=20)


def test_shared_status_list_and_validation(owner, sales, my_lead):
    st = requests.get(f"{API}/lead-statuses", headers=sales, timeout=20).json()
    assert st["statuses"] == ["new", "contacted", "qualified", "won", "lost"]
    for bad in ("working", "converted", "interested", "bogus"):
        assert requests.patch(f"{API}/leads/{my_lead['id']}", json={"status": bad}, headers=owner, timeout=20).status_code == 422
        assert requests.patch(f"{API}/mobile/leads/{my_lead['id']}", json={"status": bad}, headers=sales, timeout=20).status_code == 422
    assert requests.get(f"{API}/leads/{my_lead['id']}", headers=owner, timeout=20).json()["status"] == "new"


def test_schedule_requires_due_and_valid_kind(sales, my_lead):
    assert _fu(sales, my_lead["id"], kind="call", note="x").status_code == 422
    assert _fu(sales, my_lead["id"], kind="fax", due_at=datetime.now(timezone.utc).isoformat()).status_code == 422
    assert _fu(sales, my_lead["id"], kind="call", status="cancelled", due_at=datetime.now(timezone.utc).isoformat()).status_code == 422


def test_sales_cannot_touch_unassigned_lead(sales, other_lead, owner):
    assert requests.get(f"{API}/leads/{other_lead['id']}/follow-ups", headers=sales, timeout=20).status_code == 403
    assert _fu(sales, other_lead["id"], due_at=datetime.now(timezone.utc).isoformat()).status_code == 403
    r = _fu(owner, other_lead["id"], due_at=datetime.now(timezone.utc).isoformat(), note="owner fu")
    assert r.status_code == 201
    assert requests.patch(f"{API}/follow-ups/{r.json()['id']}", json={"status": "done"}, headers=sales, timeout=20).status_code == 403
    assert requests.patch(f"{API}/follow-ups/not-a-uuid", json={"status": "done"}, headers=owner, timeout=20).status_code == 404


def test_several_follow_ups_overdue_today_and_dashboards(owner, sales, my_lead, other_lead):
    now = datetime.now(timezone.utc)
    od = _fu(sales, my_lead["id"], kind="call", note="TEST overdue", due_at=(now - timedelta(days=2)).isoformat())
    td = _fu(sales, my_lead["id"], kind="text", note="TEST later", due_at=(now + timedelta(days=5)).isoformat())
    assert od.status_code == 201 and td.status_code == 201
    lst = requests.get(f"{API}/leads/{my_lead['id']}/follow-ups", headers=sales, timeout=20).json()
    assert {f["id"] for f in lst} >= {od.json()["id"], td.json()["id"]}

    d = requests.get(f"{API}/dashboard/attention", params={"tz": TZ}, headers=sales, timeout=30).json()
    ids = [i["id"] for i in d["follow_ups"]["items"]]
    assert od.json()["id"] in ids and td.json()["id"] not in ids
    assert next(i for i in d["follow_ups"]["items"] if i["id"] == od.json()["id"])["when"] == "overdue"
    assert all(i["lead_id"] != other_lead["id"] for i in d["follow_ups"]["items"])  # sales sees own leads only
    assert "unassigned" not in d and "overdue_by_rep" not in d

    o = requests.get(f"{API}/dashboard/attention", params={"tz": TZ}, headers=owner, timeout=30).json()
    assert od.json()["id"] in [i["id"] for i in o["follow_ups"]["items"]] or o["follow_ups"]["count"] > 20
    assert any(r["count"] >= 1 for r in o["overdue_by_rep"])
    assert o["unassigned"]["count"] >= 1

    md = requests.get(f"{API}/mobile/my-day", params={"tz": TZ}, headers=sales, timeout=30).json()
    assert od.json()["id"] in [i["id"] for i in md["follow_ups"]["items"]]

    leads = requests.get(f"{API}/leads", params={"tz": TZ}, headers=sales, timeout=30).json()
    row = next(l for l in leads if l["id"] == my_lead["id"])
    assert row["open_follow_ups"] == 2 and row["next_action"]["when"] == "overdue" and "TEST overdue" in row["next_action"]["text"]
    mrow = next(l for l in requests.get(f"{API}/mobile/leads", headers=sales, timeout=30).json() if l["id"] == my_lead["id"])
    assert mrow["next_action"]["text"] == row["next_action"]["text"]


def test_complete_idempotent_conflict_and_contact_log(sales, owner, my_lead):
    fid = str(uuid.uuid4())
    body = {"id": fid, "kind": "call", "note": "TEST offline", "due_at": datetime.now(timezone.utc).isoformat()}
    a, b = _fu(sales, my_lead["id"], **body), _fu(sales, my_lead["id"], **body)  # offline replay
    assert a.status_code == 201 and b.json()["id"] == fid
    assert len([f for f in requests.get(f"{API}/leads/{my_lead['id']}/follow-ups", headers=sales, timeout=20).json() if f["id"] == fid]) == 1
    stale = a.json()["if_match"]
    r = requests.patch(f"{API}/follow-ups/{fid}", json={"note": "TEST moved"}, headers=owner, timeout=20)
    assert r.status_code == 200
    r = requests.patch(f"{API}/follow-ups/{fid}", json={"note": "TEST field edit"}, headers={**sales, "If-Match": stale}, timeout=20)
    assert r.status_code == 409 and r.json()["detail"]["server"]["note"] == "TEST moved"
    r = requests.patch(f"{API}/follow-ups/{fid}", json={"status": "done", "outcome": "Left voicemail"}, headers=sales, timeout=20)
    assert r.status_code == 200 and r.json()["completed_at"]
    again = requests.patch(f"{API}/follow-ups/{fid}", json={"status": "done"}, headers=sales, timeout=20)
    assert again.status_code == 200 and again.json()["completed_at"] == r.json()["completed_at"]
    assert requests.get(f"{API}/leads/{my_lead['id']}", headers=sales, timeout=20).json()["status"] == "contacted"
    log = _fu(sales, my_lead["id"], kind="visit", status="done", note="TEST door knock")
    assert log.status_code == 201 and log.json()["status"] == "done"


def test_field_note_appends(sales, my_lead):
    for n in ("TEST first note", "TEST second note"):
        assert requests.patch(f"{API}/mobile/leads/{my_lead['id']}", json={"append_note": n}, headers=sales, timeout=20).status_code == 200
    notes = requests.get(f"{API}/mobile/leads/{my_lead['id']}", headers=sales, timeout=20).json()["notes"]
    assert "TEST first note" in notes and "TEST second note" in notes


def test_scheduled_inspection_lifecycle(sales, owner, my_lead, other_lead):
    assert requests.post(f"{API}/inspections", json={"lead_id": my_lead["id"], "status": "scheduled"}, headers=sales, timeout=20).status_code == 422
    assert requests.post(f"{API}/inspections", json={"lead_id": other_lead["id"], "status": "scheduled",
                                                     "inspection_date": datetime.now(timezone.utc).isoformat()}, headers=sales, timeout=20).status_code == 403
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = requests.post(f"{API}/mobile/inspections", json={"lead_id": my_lead["id"], "property_id": my_lead["property_id"], "status": "scheduled",
                                                         "inspection_date": when, "inspector": "TEST Rep"}, headers=sales, timeout=20)
    assert r.status_code == 201 and r.json()["status"] == "scheduled"
    iid = r.json()["id"]
    d = requests.get(f"{API}/dashboard/attention", params={"tz": TZ}, headers=sales, timeout=30).json()
    assert iid in [i["id"] for i in d["inspections"]["items"]]
    wf = requests.get(f"{API}/leads/{my_lead['id']}/workflow", headers=sales, timeout=20).json()["facts"]
    assert wf["inspections"] == 0 and wf["inspections_scheduled"] == 1
    det = requests.get(f"{API}/mobile/leads/{my_lead['id']}", headers=sales, timeout=20).json()
    assert iid in [i["id"] for i in det["scheduled_inspections"]]
    r = requests.patch(f"{API}/inspections/{iid}", json={"findings": "TEST hail damage", "roof_condition": "Fair"}, headers=sales, timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "completed"
    d = requests.get(f"{API}/dashboard/attention", params={"tz": TZ}, headers=sales, timeout=30).json()
    assert iid not in [i["id"] for i in d["inspections"]["items"]]
    assert requests.get(f"{API}/leads/{my_lead['id']}/workflow", headers=sales, timeout=20).json()["facts"]["inspections"] == 1


def test_proposal_attention_after_three_days(owner, sales, my_lead):
    assert requests.post(f"{API}/customers/from-lead/{my_lead['id']}", headers=owner, timeout=20).status_code in (200, 201)
    lead = requests.get(f"{API}/leads/{my_lead['id']}", headers=owner, timeout=20).json()
    assert lead["status"] in ("contacted", "qualified")  # creating the customer no longer marks a lead Won
    est = requests.post(f"{API}/estimates", json={"lead_id": my_lead["id"], "customer_id": lead["customer_id"], "tax_rate": 0,
                                                  "items": [{"description": "TEST roof", "quantity": 1, "selling_unit_price": 100}]}, headers=owner, timeout=20)
    assert est.status_code in (200, 201), est.text
    q = requests.post(f"{API}/quotes", json={"estimate_id": est.json()["id"]}, headers=owner, timeout=20)
    assert q.status_code in (200, 201), q.text
    qid = q.json()["id"]
    d = requests.get(f"{API}/dashboard/attention", headers=sales, timeout=30).json()
    assert qid not in [p["id"] for p in d["proposals"]["items"]]  # fresh draft: not flagged yet
    _sql("update quotes set created_at = now() - interval '4 days' where id = cast(:id as uuid)", id=qid)
    d = requests.get(f"{API}/dashboard/attention", headers=sales, timeout=30).json()
    item = next(p for p in d["proposals"]["items"] if p["id"] == qid)
    assert item["reason"] == "Not sent for 3+ days"
    assert requests.put(f"{API}/quotes/{qid}", json={"status": "sent"}, headers=owner, timeout=20).status_code == 200
    _sql("update quotes set issue_date = now() - interval '4 days', updated_at = now() - interval '4 days' where id = cast(:id as uuid)", id=qid)
    d = requests.get(f"{API}/dashboard/attention", headers=sales, timeout=30).json()
    assert next(p for p in d["proposals"]["items"] if p["id"] == qid)["reason"] == "No answer for 3+ days"
    r = requests.post(f"{API}/quotes/{qid}/accept", json={"acceptance_name": "TEST Buyer"}, headers=owner, timeout=30)
    assert r.status_code == 200, r.text
    assert requests.get(f"{API}/leads/{my_lead['id']}", headers=owner, timeout=20).json()["status"] == "won"
    d = requests.get(f"{API}/dashboard/attention", headers=sales, timeout=30).json()
    assert qid not in [p["id"] for p in d["proposals"]["items"]]
    assert all(i["lead_id"] != my_lead["id"] for i in d["follow_ups"]["items"])  # won leads leave the follow-up lists
