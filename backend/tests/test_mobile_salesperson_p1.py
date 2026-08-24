"""P1 — Mobile salesperson security / API boundary.

Backend-authoritative access control: a `sales` user can only reach records assigned/authorized to
them, and CANNOT reach another salesperson's Lead/Job/Property/Inspection/Photo by direct UUID.
Integration style (requests against the running backend); seeds users/territory/properties/leads/
jobs/inspections directly via the async DB and mints tokens with create_access_token (same PG).
"""
import os
import io
import uuid
import base64
import asyncio
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

TERR = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
SEC_A = {"type": "Polygon", "coordinates": [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]]}
SEC_B = {"type": "Polygon", "coordinates": [[[5, 5], [5, 8], [8, 8], [8, 5], [5, 5]]]}

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _seed():
    from db import SessionLocal
    from models import User, Territory, Property, Lead, Job, Inspection
    from core import hash_password
    async with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:8]
        owner = User(email=f"mown_{sfx}@t.io", password_hash=hash_password("x"), full_name="Own", role="owner")
        repA = User(email=f"mrepA_{sfx}@t.io", password_hash=hash_password("x"), full_name="Rep A", role="sales")
        repB = User(email=f"mrepB_{sfx}@t.io", password_hash=hash_password("x"), full_name="Rep B", role="sales")
        db.add_all([owner, repA, repB]); await db.flush()
        terr = Territory(name=f"MT-{sfx}", geometry=TERR, created_by=owner.email)
        db.add(terr); await db.flush()
        pA1 = Property(territory_id=terr.id, formatted_address=f"PA1-{sfx}", latitude=2, longitude=2)
        pB1 = Property(territory_id=terr.id, formatted_address=f"PB1-{sfx}", latitude=6, longitude=6)
        db.add_all([pA1, pB1]); await db.flush()
        leadA = Lead(name="Lead A", status="new", assigned_user_id=repA.id, property_id=pA1.id, created_by=repA.email)
        leadB = Lead(name="Lead B", status="new", assigned_user_id=repB.id, property_id=pB1.id, created_by=repB.email)
        leadArch = Lead(name="Lead A archived", status="archived", assigned_user_id=repA.id, created_by=repA.email)
        jobA = Job(number=f"JOB-{sfx}-A", status="scheduled", assigned_user_id=repA.id, scope="Job A")
        jobB = Job(number=f"JOB-{sfx}-B", status="scheduled", assigned_user_id=repB.id, scope="Job B")
        db.add_all([leadA, leadB, leadArch, jobA, jobB]); await db.flush()
        inspB = Inspection(lead_id=leadB.id, property_id=pB1.id, roof_condition="fair", findings="B only", created_by=repB.email)
        db.add(inspB)
        await db.commit()
        return {
            "owner": (str(owner.id), owner.email, "owner"),
            "repA": (str(repA.id), repA.email, "sales"),
            "repB": (str(repB.id), repB.email, "sales"),
            "terr": str(terr.id), "pA1": str(pA1.id), "pB1": str(pB1.id),
            "leadA": str(leadA.id), "leadB": str(leadB.id), "leadArch": str(leadArch.id),
            "jobA": str(jobA.id), "jobB": str(jobB.id), "inspB": str(inspB.id),
        }


def _tok(triple):
    from core import create_access_token
    uid, email, role = triple
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


S = None
SEC = {}


def setup_module(_):
    global S, SEC
    S = run(_seed())
    a = requests.post(f"{API}/canvass-sections", headers=_tok(S["owner"]),
                      json={"territory_id": S["terr"], "name": "Sec A", "geometry": SEC_A, "assigned_user_id": S["repA"][0]}, timeout=20)
    assert a.status_code == 201, a.text
    b = requests.post(f"{API}/canvass-sections", headers=_tok(S["owner"]),
                      json={"territory_id": S["terr"], "name": "Sec B", "geometry": SEC_B, "assigned_user_id": S["repB"][0]}, timeout=20)
    assert b.status_code == 201, b.text
    SEC = {"A": a.json()["id"], "B": b.json()["id"]}


def teardown_module(_):
    for sid in SEC.values():
        requests.delete(f"{API}/canvass-sections/{sid}", headers=_tok(S["owner"]), timeout=20)


# ---------------- Leads ----------------
def test_sales_sees_only_own_active_leads():
    r = requests.get(f"{API}/mobile/leads", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 200
    ids = [l["id"] for l in r.json()]
    assert S["leadA"] in ids
    assert S["leadB"] not in ids          # cannot see another rep's lead
    assert S["leadArch"] not in ids       # archived excluded from field list


def test_sales_cannot_get_another_lead_by_uuid():
    r = requests.get(f"{API}/mobile/leads/{S['leadB']}", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 403, r.text
    assert requests.get(f"{API}/mobile/leads/{S['leadA']}", headers=_tok(S["repA"]), timeout=20).status_code == 200


def test_sales_cannot_patch_another_lead():
    r = requests.patch(f"{API}/mobile/leads/{S['leadB']}", headers=_tok(S["repA"]), json={"notes": "hax"}, timeout=20)
    assert r.status_code == 403, r.text
    # also the Office lead PATCH is backend-authoritative
    r2 = requests.patch(f"{API}/leads/{S['leadB']}", headers=_tok(S["repA"]), json={"notes": "hax"}, timeout=20)
    assert r2.status_code == 403, r2.text


def test_sales_cannot_archive_another_lead():
    r = requests.delete(f"{API}/mobile/leads/{S['leadB']}", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 403, r.text


def test_sales_created_lead_is_assigned_to_caller():
    r = requests.post(f"{API}/mobile/leads", headers=_tok(S["repA"]),
                      json={"name": "Fresh", "assigned_user_id": S["repB"][0]}, timeout=20)  # spoof attempt
    assert r.status_code == 201, r.text
    assert r.json()["assigned_user_id"] == S["repA"][0]  # server ignores spoof, assigns caller


def test_sales_cannot_reassign_lead():
    # Office assign endpoint is management-only; sales are rejected.
    r = requests.put(f"{API}/leads/{S['leadA']}/assign", headers=_tok(S["repA"]),
                     json={"user_id": S["repB"][0]}, timeout=20)
    assert r.status_code == 403, r.text


def test_sales_archive_own_lead_soft():
    mk = requests.post(f"{API}/mobile/leads", headers=_tok(S["repA"]), json={"name": "ToArchive"}, timeout=20).json()
    r = requests.delete(f"{API}/mobile/leads/{mk['id']}", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 200 and r.json()["status"] == "archived"


# ---------------- Jobs ----------------
def test_sales_sees_only_own_jobs():
    r = requests.get(f"{API}/mobile/jobs", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 200
    ids = [j["id"] for j in r.json()]
    assert S["jobA"] in ids and S["jobB"] not in ids


def test_sales_cannot_get_another_job_by_uuid():
    assert requests.get(f"{API}/mobile/jobs/{S['jobB']}", headers=_tok(S["repA"]), timeout=20).status_code == 403
    assert requests.get(f"{API}/mobile/jobs/{S['jobA']}", headers=_tok(S["repA"]), timeout=20).status_code == 200


def test_sales_cannot_patch_another_job():
    r = requests.patch(f"{API}/mobile/jobs/{S['jobB']}", headers=_tok(S["repA"]), json={"notes": "x"}, timeout=20)
    assert r.status_code == 403, r.text


def test_no_blank_job_create_on_mobile():
    # Accepted-quote -> Job workflow is preserved; there is no mobile blank-create endpoint.
    r = requests.post(f"{API}/mobile/jobs", headers=_tok(S["repA"]), json={"scope": "x"}, timeout=20)
    assert r.status_code in (404, 405), r.text


# ---------------- Canvass / Property ----------------
def test_sales_sees_only_assigned_sections():
    ra = requests.get(f"{API}/mobile/canvass-sections", headers=_tok(S["repA"]), timeout=20).json()["sections"]
    ida = [s["id"] for s in ra]
    assert SEC["A"] in ida and SEC["B"] not in ida


def test_sales_cannot_read_another_section_properties():
    r = requests.get(f"{API}/mobile/canvass-sections/{SEC['B']}/properties", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 403, r.text


def test_sales_cannot_get_another_section_property_by_uuid():
    # pB1 belongs only to Rep B's section -> Rep A must be denied by the backend.
    r = requests.get(f"{API}/mobile/properties/{S['pB1']}", headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 403, r.text
    # Rep A can read a property in their own section.
    assert requests.get(f"{API}/mobile/properties/{S['pA1']}", headers=_tok(S["repA"]), timeout=20).status_code == 200
    # Rep B can read their own.
    assert requests.get(f"{API}/mobile/properties/{S['pB1']}", headers=_tok(S["repB"]), timeout=20).status_code == 200


def test_no_mobile_section_edit_endpoints_and_office_blocks_sales():
    # There is no mobile draw/edit route; the Office canvass routes reject sales entirely.
    assert requests.post(f"{API}/canvass-sections", headers=_tok(S["repA"]),
                         json={"territory_id": S["terr"], "name": "X", "geometry": SEC_A}, timeout=20).status_code == 403
    assert requests.put(f"{API}/canvass-sections/{SEC['A']}", headers=_tok(S["repA"]),
                        json={"name": "X"}, timeout=20).status_code == 403
    assert requests.delete(f"{API}/canvass-sections/{SEC['A']}", headers=_tok(S["repA"]), timeout=20).status_code == 403


# ---------------- Inspections / Photos ----------------
def test_sales_cannot_patch_inspection_on_another_lead():
    r = requests.patch(f"{API}/mobile/inspections/{S['inspB']}", headers=_tok(S["repA"]), json={"findings": "x"}, timeout=20)
    assert r.status_code == 403, r.text
    assert requests.patch(f"{API}/mobile/inspections/{S['inspB']}", headers=_tok(S["repB"]), json={"findings": "ok"}, timeout=20).status_code == 200


def test_sales_cannot_list_or_upload_photos_for_inaccessible_lead():
    r = requests.get(f"{API}/mobile/photos", params={"record_type": "lead", "record_id": S["leadB"]}, headers=_tok(S["repA"]), timeout=20)
    assert r.status_code == 403, r.text
    files = {"file": ("t.png", io.BytesIO(PNG_BYTES), "image/png")}
    data = {"record_type": "lead", "record_id": S["leadB"]}
    up = requests.post(f"{API}/mobile/photos", files=files, data=data, headers=_tok(S["repA"]), timeout=30)
    assert up.status_code == 403, up.text


# ---------------- Create-from-property + dedupe + idempotency ----------------
def test_create_lead_from_authorized_property_dedupes():
    key = f"lead-{uuid.uuid4()}"
    h = {**_tok(S["repA"]), "Idempotency-Key": key}
    r1 = requests.post(f"{API}/mobile/leads", headers=h, json={"property_id": S["pA1"]}, timeout=20)
    assert r1.status_code == 201, r1.text
    lid = r1.json()["id"]
    assert r1.json()["property_id"] == S["pA1"] and r1.json()["assigned_user_id"] == S["repA"][0]
    # idempotent replay -> same id
    r2 = requests.post(f"{API}/mobile/leads", headers=h, json={"property_id": S["pA1"]}, timeout=20)
    assert r2.status_code == 201 and r2.json()["id"] == lid
    # new key, same property -> reuse existing (no duplicate)
    r3 = requests.post(f"{API}/mobile/leads", headers={**_tok(S["repA"]), "Idempotency-Key": f"lead-{uuid.uuid4()}"},
                       json={"property_id": S["pA1"]}, timeout=20)
    assert r3.status_code == 201 and r3.json()["id"] == lid and r3.json().get("existing") is True


def test_create_lead_from_unauthorized_property_denied():
    r = requests.post(f"{API}/mobile/leads", headers=_tok(S["repA"]), json={"property_id": S["pB1"]}, timeout=20)
    assert r.status_code == 403, r.text


# ---------------- Lead update + optimistic-conflict (If-Match) ----------------
def test_mobile_lead_update_and_conflict():
    cur = requests.get(f"{API}/mobile/leads/{S['leadA']}", headers=_tok(S["repA"]), timeout=20).json()
    ok = requests.patch(f"{API}/mobile/leads/{S['leadA']}", headers={**_tok(S["repA"]), "If-Match": cur["if_match"]},
                        json={"notes": "field update"}, timeout=20)
    assert ok.status_code == 200 and ok.json()["notes"] == "field update"
    stale = requests.patch(f"{API}/mobile/leads/{S['leadA']}", headers={**_tok(S["repA"]), "If-Match": "1999-01-01T00:00:00+00:00"},
                           json={"notes": "stale"}, timeout=20)
    assert stale.status_code == 409, stale.text


# ---------------- Inspection scoping (mobile + office hardening) ----------------
def test_mobile_inspection_list_scoping():
    # sales must scope by their own lead/property; cannot read another rep's lead inspections
    assert requests.get(f"{API}/mobile/inspections", headers=_tok(S["repA"]), timeout=20).status_code == 422
    assert requests.get(f"{API}/mobile/inspections", params={"lead_id": S["leadB"]}, headers=_tok(S["repA"]), timeout=20).status_code == 403
    r = requests.get(f"{API}/mobile/inspections", params={"lead_id": S["leadB"]}, headers=_tok(S["repB"]), timeout=20)
    assert r.status_code == 200 and any(i["id"] == S["inspB"] for i in r.json())


def test_mobile_inspection_get_by_uuid_denied():
    assert requests.get(f"{API}/mobile/inspections/{S['inspB']}", headers=_tok(S["repA"]), timeout=20).status_code == 403
    assert requests.get(f"{API}/mobile/inspections/{S['inspB']}", headers=_tok(S["repB"]), timeout=20).status_code == 200


def test_office_inspections_no_sales_enumeration():
    # Office inspections endpoints are backend-authoritative too (defense in depth).
    assert requests.get(f"{API}/inspections", headers=_tok(S["repA"]), timeout=20).status_code == 403
    assert requests.get(f"{API}/inspections", params={"lead_id": S["leadB"]}, headers=_tok(S["repA"]), timeout=20).status_code == 403
    assert requests.get(f"{API}/inspections/{S['inspB']}", headers=_tok(S["repA"]), timeout=20).status_code == 403
