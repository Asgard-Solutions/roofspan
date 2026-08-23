"""Canvass Sections: CRUD, membership, overlap, containment, RBAC, mobile visibility.

Integration style (requests against the running backend), matching the existing suite.
Seeds territory/properties/users directly via the async DB (same PG the server uses).
"""
import os
import uuid
import asyncio
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

TERR = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
SEC_A = {"type": "Polygon", "coordinates": [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]]}
SEC_B = {"type": "Polygon", "coordinates": [[[5, 5], [5, 8], [8, 8], [8, 5], [5, 5]]]}
SEC_OVERLAP = {"type": "Polygon", "coordinates": [[[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]]]}
OUTSIDE = {"type": "Polygon", "coordinates": [[[20, 20], [20, 22], [22, 22], [22, 20], [20, 20]]]}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)


async def _seed():
    from db import SessionLocal
    from models import User, Territory, Property
    from core import hash_password
    async with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:8]
        owner = User(email=f"cvown_{sfx}@t.io", password_hash=hash_password("x"), full_name="Own", role="owner")
        rep = User(email=f"cvrep_{sfx}@t.io", password_hash=hash_password("x"), full_name="Mike Rep", role="sales")
        rep2 = User(email=f"cvrep2_{sfx}@t.io", password_hash=hash_password("x"), full_name="Sara Rep", role="sales")
        db.add_all([owner, rep, rep2]); await db.flush()
        terr = Territory(name=f"CT-{sfx}", geometry=TERR, created_by=owner.email)
        db.add(terr); await db.flush()
        db.add_all([
            Property(territory_id=terr.id, formatted_address="P1", latitude=2, longitude=2),
            Property(territory_id=terr.id, formatted_address="P2", latitude=3, longitude=3),
            Property(territory_id=terr.id, formatted_address="P3", latitude=6, longitude=6),
            Property(territory_id=terr.id, formatted_address="P4 no coords", latitude=None, longitude=None),
            Property(territory_id=terr.id, formatted_address="P-DNK", latitude=2.5, longitude=2.5, do_not_knock=True),
        ])
        await db.commit()
        return {"owner": (str(owner.id), owner.email, "owner"),
                "rep": (str(rep.id), rep.email, "sales"),
                "rep2": (str(rep2.id), rep2.email, "sales"),
                "terr": str(terr.id)}


def _tok(triple):
    from core import create_access_token
    uid, email, role = triple
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


S = None


def setup_module(_):
    global S
    S = run(_seed())


def _create(headers, terr_id, name, geom, assigned=None):
    body = {"territory_id": terr_id, "name": name, "geometry": geom}
    if assigned:
        body["assigned_user_id"] = assigned
    return requests.post(f"{API}/canvass-sections", json=body, headers=headers, timeout=20)


def test_preview_membership_and_containment():
    r = requests.post(f"{API}/canvass-sections/preview", headers=_tok(S["owner"]),
                      json={"territory_id": S["terr"], "geometry": SEC_A}, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["property_count"] == 3 and d["do_not_knock_count"] == 1
    r2 = requests.post(f"{API}/canvass-sections/preview", headers=_tok(S["owner"]),
                       json={"territory_id": S["terr"], "geometry": OUTSIDE}, timeout=20)
    assert r2.status_code == 422


def test_sales_cannot_create():
    assert _create(_tok(S["rep"]), S["terr"], "X", SEC_A).status_code == 403


def test_invalid_territory_and_polygon():
    assert _create(_tok(S["owner"]), str(uuid.uuid4()), "X", SEC_A).status_code == 404
    bad = {"type": "Polygon", "coordinates": [[[1, 1], [1, 2], [1, 1]]]}
    assert _create(_tok(S["owner"]), S["terr"], "X", bad).status_code == 422


def test_create_assign_membership_and_dnk():
    r = _create(_tok(S["owner"]), S["terr"], "Section A", SEC_A, assigned=S["rep"][0])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["property_count"] == 3 and d["do_not_knock_count"] == 1
    assert d["assigned_user_name"] == "Mike Rep"
    pr = requests.get(f"{API}/canvass-sections/{d['id']}/properties", headers=_tok(S["owner"]), timeout=20)
    assert len([p for p in pr.json() if p["do_not_knock"]]) == 1
    requests.delete(f"{API}/canvass-sections/{d['id']}", headers=_tok(S["owner"]), timeout=20)


def test_overlap_blocks_save():
    a = _create(_tok(S["owner"]), S["terr"], "A", SEC_A, assigned=S["rep"][0])
    assert a.status_code == 201
    aid = a.json()["id"]
    prev = requests.post(f"{API}/canvass-sections/preview", headers=_tok(S["owner"]),
                         json={"territory_id": S["terr"], "geometry": SEC_OVERLAP}, timeout=20).json()
    assert prev["conflict_count"] >= 1 and prev["conflicts"][0]["section_name"] == "A"
    b = _create(_tok(S["owner"]), S["terr"], "B", SEC_OVERLAP)
    assert b.status_code == 409
    requests.delete(f"{API}/canvass-sections/{aid}", headers=_tok(S["owner"]), timeout=20)


def test_edit_geometry_recomputes():
    a = _create(_tok(S["owner"]), S["terr"], "A", SEC_A).json()
    r = requests.put(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), json={"geometry": SEC_B}, timeout=20)
    assert r.status_code == 200 and r.json()["property_count"] == 1
    requests.delete(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), timeout=20)


def test_reassign_and_unassign():
    a = _create(_tok(S["owner"]), S["terr"], "A", SEC_A, assigned=S["rep"][0]).json()
    r = requests.put(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), json={"assigned_user_id": S["rep2"][0]}, timeout=20)
    assert r.json()["assigned_user_id"] == S["rep2"][0]
    r2 = requests.put(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), json={"assigned_user_id": None}, timeout=20)
    assert r2.json()["assigned_user_id"] is None
    requests.delete(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), timeout=20)


def test_delete_preserves_properties():
    a = _create(_tok(S["owner"]), S["terr"], "A", SEC_A).json()
    assert requests.delete(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), timeout=20).status_code == 200
    # properties still present in territory
    terr_geo = requests.get(f"{API}/properties/geojson?territory_id={S['terr']}", headers=_tok(S["owner"]), timeout=20).json()
    assert len(terr_geo["features"]) == 4  # 4 with coords


def test_mobile_sales_visibility_isolation():
    a = _create(_tok(S["owner"]), S["terr"], "A", SEC_A, assigned=S["rep"][0]).json()
    r = requests.get(f"{API}/mobile/canvass-sections", headers=_tok(S["rep"]), timeout=20)
    assert a["id"] in [s["id"] for s in r.json()["sections"]]
    r2 = requests.get(f"{API}/mobile/canvass-sections", headers=_tok(S["rep2"]), timeout=20)
    assert a["id"] not in [s["id"] for s in r2.json()["sections"]]
    r3 = requests.get(f"{API}/mobile/canvass-sections/{a['id']}/properties", headers=_tok(S["rep2"]), timeout=20)
    assert r3.status_code == 403
    r4 = requests.get(f"{API}/mobile/canvass-sections/{a['id']}/properties", headers=_tok(S["rep"]), timeout=20)
    assert r4.status_code == 200 and any(f["properties"]["do_not_knock"] for f in r4.json()["features"])
    requests.delete(f"{API}/canvass-sections/{a['id']}", headers=_tok(S["owner"]), timeout=20)
