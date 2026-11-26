"""Iteration 138: gap cases for Won/Lost auto-cancel + status-correction data checks."""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
REP_A = ("sales_bk@example.com", "SalesBk#2026")
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


def _lead(owner, rep):
    r = requests.post(f"{API}/properties", json={"address_line1": f"{uuid.uuid4().hex[:6]} TEST_Gap Way", "city": "Austin", "state": "TX",
                                                 "zip_code": "78701", "latitude": 30.27, "longitude": -97.74}, headers=owner, timeout=20)
    lead = requests.post(f"{API}/properties/{r.json()['id']}/convert-to-lead", json={"name": f"TEST_Gap {uuid.uuid4().hex[:6]}"}, headers=owner, timeout=20).json()
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
    return [x for x in r.json()["items"] if str(x.get("entity_id")) == lid]


# (The one-off 122-lead status correction is verified by scripts/fix_converted_won_leads.py --dry-run, not by
#  live-data assertions that concurrent suites could disturb.)


# Office: a new open follow-up (no client id) on a Won lead is stored cancelled, never outstanding
def test_office_create_on_won_lead_is_cancelled(owner, rep_a):
    lid = _lead(owner, rep_a)["id"]
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "won"}, headers=rep_a, timeout=20).status_code == 200
    f = _fu(rep_a, lid, kind="call", note="TEST on won", due_at=NOW.isoformat())
    assert f["status"] == "cancelled" and f["outcome"] == "Lead marked Won"
    # Won -> Lost: already-cancelled keep 'Lead marked Won'; no auto_cancel audit since nothing open
    assert requests.patch(f"{API}/leads/{lid}", json={"status": "lost"}, headers=rep_a, timeout=20).status_code == 200
    assert _fus(owner, lid)[f["id"]]["outcome"] == "Lead marked Won"
    assert _audit(owner, lid, "followup.auto_cancel") == []


# Field: stale If-Match on lead PATCH returns 409 and does NOT cancel follow-ups
def test_field_stale_if_match_does_not_cancel(owner, rep_a):
    lid = _lead(owner, rep_a)["id"]
    det = requests.get(f"{API}/mobile/leads/{lid}", headers=rep_a, timeout=20).json()
    o = _fu(rep_a, lid, kind="call", note="TEST stale", due_at=NOW.isoformat())
    assert requests.patch(f"{API}/leads/{lid}", json={"notes": "TEST changed"}, headers=owner, timeout=20).status_code == 200
    r = requests.patch(f"{API}/mobile/leads/{lid}", json={"status": "lost"}, headers={**rep_a, "If-Match": det["if_match"]}, timeout=20)
    assert r.status_code == 409
    assert _fus(owner, lid)[o["id"]]["status"] == "open"
    assert requests.get(f"{API}/leads/{lid}", headers=owner, timeout=20).json()["status"] != "lost"


# Field: PATCH {status:'open'} on auto-cancelled returns 409 with server.status cancelled
def test_field_reopen_attempt_409_server_payload(owner, rep_a):
    lid = _lead(owner, rep_a)["id"]
    o = _fu(rep_a, lid, kind="call", note="TEST r", due_at=NOW.isoformat())
    det = requests.get(f"{API}/mobile/leads/{lid}", headers=rep_a, timeout=20).json()
    assert requests.patch(f"{API}/mobile/leads/{lid}", json={"status": "lost"}, headers={**rep_a, "If-Match": det["if_match"]}, timeout=20).status_code == 200
    r = requests.patch(f"{API}/follow-ups/{o['id']}", json={"status": "open"}, headers=rep_a, timeout=20)
    assert r.status_code == 409 and r.json()["detail"]["server"]["status"] == "cancelled"
    # reopen lead -> still cancelled, then new create stays open
    det = requests.get(f"{API}/mobile/leads/{lid}", headers=rep_a, timeout=20).json()
    assert requests.patch(f"{API}/mobile/leads/{lid}", json={"status": "contacted"}, headers={**rep_a, "If-Match": det["if_match"]}, timeout=20).status_code == 200
    assert _fus(owner, lid)[o["id"]]["status"] == "cancelled"
    assert _fu(rep_a, lid, id=str(uuid.uuid4()), kind="call", due_at=NOW.isoformat())["status"] == "open"


# Public share-link acceptance (no user) cancels follow-ups and writes audit without error
def test_public_link_acceptance_cancels(owner, rep_a):
    lid = _lead(owner, rep_a)["id"]
    o = _fu(rep_a, lid, kind="call", note="TEST public", due_at=(NOW + timedelta(days=1)).isoformat())
    assert requests.post(f"{API}/customers/from-lead/{lid}", headers=owner, timeout=20).status_code in (200, 201)
    cust = requests.get(f"{API}/leads/{lid}", headers=owner, timeout=20).json()["customer_id"]
    est = requests.post(f"{API}/estimates", json={"lead_id": lid, "customer_id": cust, "tax_rate": 0,
                                                  "items": [{"description": "TEST roof", "quantity": 1, "selling_unit_price": 100}]}, headers=owner, timeout=20).json()
    q = requests.post(f"{API}/quotes", json={"estimate_id": est["id"]}, headers=owner, timeout=20).json()
    tok = requests.get(f"{API}/quotes/{q['id']}/share-link", headers=owner, timeout=20).json()["token"]
    r = requests.post(f"{API}/public/proposals/{tok}/accept", json={"acceptance_name": "TEST Buyer", "agreed": True}, timeout=30)
    assert r.status_code == 200, r.text
    assert requests.get(f"{API}/leads/{lid}", headers=owner, timeout=20).json()["status"] == "won"
    f = _fus(owner, lid)[o["id"]]
    assert f["status"] == "cancelled" and f["outcome"] == "Lead marked Won"
    logs = _audit(owner, lid, "followup.auto_cancel")
    assert len(logs) == 1 and logs[0]["detail"]["follow_up_ids"] == [o["id"]]
