"""P0 coverage for the unified Field area selector: GET /api/mobile/map/areas.

Contract (server-authoritative):
  - "canvass_section" areas: the caller's ASSIGNED active sections (sales) / all active (management),
    carrying real stored GeoJSON geometry + polygon bounds.
  - "zip" areas: Office-loaded ZIP property datasets the caller is authorized to work. A SALES user is
    scoped STRICTLY to properties inside their assigned territories; the ZIP property_count + bounds are
    computed from those in-scope properties ONLY (a ZIP straddling the assignment boundary is never
    widened). Management sees all ZIPs. ZIP carries NO polygon (geometry null) — bounds are derived from
    member property coordinates.
  - Cross-user isolation: a sales user never sees another rep's sections or out-of-scope ZIP areas.
"""
import os
import uuid
import asyncio
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

TERR_A = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
TERR_B = {"type": "Polygon", "coordinates": [[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]]}
SEC_A = {"type": "Polygon", "coordinates": [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]]}
PWD = "TestP@ss1"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _seed():
    from db import SessionLocal
    from models import User, Territory, Property, CanvassSection
    from core import hash_password
    async with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:8]
        owner = User(email=f"areaown_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Own", role="owner")
        rep = User(email=f"arearep_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Rep A", role="sales")
        rep_other = User(email=f"areaoth_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Rep Other", role="sales")
        db.add_all([owner, rep, rep_other]); await db.flush()

        terr_a = Territory(name=f"AR-A-{sfx}", geometry=TERR_A, created_by=owner.email)
        terr_b = Territory(name=f"AR-B-{sfx}", geometry=TERR_B, created_by=owner.email)
        db.add_all([terr_a, terr_b]); await db.flush()

        zip_in = f"73{sfx[:3]}"   # ZIP present INSIDE rep's assigned territory A
        zip_out = f"74{sfx[:3]}"  # ZIP only in territory B (out of rep scope)
        # Two in-scope props (territory A) sharing zip_in, at distinct coords → real bbox.
        p1 = Property(territory_id=terr_a.id, formatted_address=f"A1-{sfx}", city="Blanchard", zip_code=zip_in,
                      latitude=2.0, longitude=2.0, do_not_knock=False)
        p2 = Property(territory_id=terr_a.id, formatted_address=f"A2-{sfx}", city="Blanchard", zip_code=zip_in,
                      latitude=3.5, longitude=3.0, do_not_knock=False)
        # A property in the SAME zip_in but in territory B (OUT of rep scope) — must NOT widen rep's ZIP.
        p_straddle = Property(territory_id=terr_b.id, formatted_address=f"Bx-{sfx}", city="Blanchard", zip_code=zip_in,
                              latitude=25.0, longitude=25.0, do_not_knock=False)
        # An out-of-scope ZIP entirely in territory B.
        p_out = Property(territory_id=terr_b.id, formatted_address=f"B1-{sfx}", city="Newcastle", zip_code=zip_out,
                         latitude=26.0, longitude=24.0, do_not_knock=False)
        db.add_all([p1, p2, p_straddle, p_out]); await db.flush()

        sec = CanvassSection(territory_id=terr_a.id, name=f"SEC-{sfx}", geometry=SEC_A,
                             assigned_user_id=rep.id, active=True, created_by=owner.email)
        db.add(sec); await db.commit()
        return {
            "owner": (str(owner.id), owner.email, "owner"),
            "rep": (str(rep.id), rep.email, "sales"),
            "rep_other": (str(rep_other.id), rep_other.email, "sales"),
            "sec": str(sec.id), "zip_in": zip_in, "zip_out": zip_out,
        }


def _tok(triple):
    from core import create_access_token
    uid, email, role = triple
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


S = None


def setup_module(_):
    global S
    S = run(_seed())


def _areas(headers):
    r = requests.get(f"{API}/mobile/map/areas", headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["areas"]


def test_requires_auth():
    r = requests.get(f"{API}/mobile/map/areas", timeout=20)
    assert r.status_code in (401, 403)


def test_sales_gets_assigned_section_with_real_polygon_and_bounds():
    areas = _areas(_tok(S["rep"]))
    sec = next((a for a in areas if a["id"] == S["sec"]), None)
    assert sec is not None, "assigned canvass section must appear for its assignee"
    assert sec["type"] == "canvass_section"
    assert sec["geometry"] and sec["geometry"]["type"] == "Polygon", "canvass area carries its real polygon"
    # Bounds cover SEC_A [[1,1]..[4,4]].
    assert sec["bounds"] == [[1, 1], [4, 4]]


def test_sales_zip_is_strictly_scoped_and_bounds_from_in_scope_props_only():
    areas = _areas(_tok(S["rep"]))
    zin = next((a for a in areas if a["type"] == "zip" and a["zip_code"] == S["zip_in"]), None)
    assert zin is not None, "rep must see the ZIP that intersects their assigned territory"
    assert zin["geometry"] is None, "ZIP area NEVER carries a polygon"
    # Only the 2 in-scope (territory A) props count — the same-ZIP territory-B prop must NOT widen it.
    assert zin["property_count"] == 2, "ZIP count must exclude out-of-scope (straddling) properties"
    # Bounds computed from in-scope coords only: lng 2..3, lat 2..3.5 (NOT stretched to 25,25).
    assert zin["bounds"] == [[2.0, 2.0], [3.0, 3.5]], f"ZIP bounds must come from in-scope props only, got {zin['bounds']}"
    assert "Blanchard" in zin["name"], "ZIP label includes the representative city"
    # The out-of-scope ZIP must NOT be visible to the rep at all.
    assert not any(a["type"] == "zip" and a["zip_code"] == S["zip_out"] for a in areas), \
        "rep must NOT see a ZIP entirely outside their assigned scope"


def test_sales_cannot_see_other_reps_section():
    areas = _areas(_tok(S["rep_other"]))
    assert not any(a["id"] == S["sec"] for a in areas), "a different rep must not see this section"
    # rep_other has no assignment → no canvass areas and no authorized ZIPs (strict).
    assert not any(a["type"] == "canvass_section" for a in areas)
    assert not any(a["type"] == "zip" for a in areas), "unassigned rep gets no ZIP areas (strict auth)"


def test_management_sees_all_sections_and_both_zips():
    areas = _areas(_tok(S["owner"]))
    assert any(a["id"] == S["sec"] for a in areas), "management sees the section"
    zips = {a["zip_code"] for a in areas if a["type"] == "zip"}
    assert S["zip_in"] in zips and S["zip_out"] in zips, "management sees all ZIP datasets"
    zin = next(a for a in areas if a["type"] == "zip" and a["zip_code"] == S["zip_in"])
    # Management ZIP count includes ALL 3 props sharing zip_in (2 in A + 1 in B).
    assert zin["property_count"] == 3, "management ZIP count spans all properties in the ZIP"
