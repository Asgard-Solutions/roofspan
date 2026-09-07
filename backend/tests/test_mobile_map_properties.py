"""P0 regression coverage for GET /api/mobile/map/properties.

Covers the RoofSpan Field "My Area" master property dataset:
 - Management (non-sales FIELD_ROLES) sees the full authorized set.
 - Sales sees ONLY properties in territories where they have an assigned ACTIVE canvass section.
 - Sales with ZERO active assigned sections gets a valid empty FeatureCollection (HTTP 200).
 - Properties with NULL lat/long are safely excluded.
 - Feature.properties contract: id, address, property_type, owner_occupied, occupancy,
   do_not_knock, last_outcome, last_visited_at.
 - Regression: /mobile/canvass-sections and /mobile/canvass-sections/{id}/properties still
   enforce sales-only isolation (403 for a section not assigned to a sales user).
"""
import os
import uuid
import asyncio
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

TERR_A = {"type": "Polygon", "coordinates": [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]}
TERR_B = {"type": "Polygon", "coordinates": [[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]]}
SEC_A = {"type": "Polygon", "coordinates": [[[1, 1], [1, 4], [4, 4], [4, 1], [1, 1]]]}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _seed():
    from db import SessionLocal
    from models import User, Territory, Property, CanvassSection, Visit
    from core import hash_password
    async with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:8]
        owner = User(email=f"mapown_{sfx}@t.io", password_hash=hash_password("x"), full_name="Own", role="owner")
        rep = User(email=f"maprep_{sfx}@t.io", password_hash=hash_password("x"), full_name="Rep A", role="sales")
        rep_zero = User(email=f"mapzero_{sfx}@t.io", password_hash=hash_password("x"), full_name="Rep Zero", role="sales")
        db.add_all([owner, rep, rep_zero]); await db.flush()

        terr_a = Territory(name=f"MAP-A-{sfx}", geometry=TERR_A, created_by=owner.email)
        terr_b = Territory(name=f"MAP-B-{sfx}", geometry=TERR_B, created_by=owner.email)
        db.add_all([terr_a, terr_b]); await db.flush()

        # Properties in terr_a
        p_owner = Property(territory_id=terr_a.id, formatted_address=f"A-owner-{sfx}",
                           latitude=2.0, longitude=2.0, property_type="single_family",
                           owner_occupied=True, do_not_knock=False)
        p_tenant = Property(territory_id=terr_a.id, formatted_address=f"A-tenant-{sfx}",
                            latitude=3.0, longitude=3.0, property_type="duplex",
                            owner_occupied=False, do_not_knock=False)
        p_dnk = Property(territory_id=terr_a.id, formatted_address=f"A-dnk-{sfx}",
                         latitude=2.5, longitude=2.5, property_type=None,
                         owner_occupied=None, do_not_knock=True)
        p_nocoords = Property(territory_id=terr_a.id, formatted_address=f"A-nocoords-{sfx}",
                              latitude=None, longitude=None, do_not_knock=False)
        # Property in terr_b (rep should NOT see it; owner should)
        p_b = Property(territory_id=terr_b.id, formatted_address=f"B-only-{sfx}",
                       latitude=25.0, longitude=25.0, do_not_knock=False)
        db.add_all([p_owner, p_tenant, p_dnk, p_nocoords, p_b]); await db.flush()

        # Assign rep to an active canvass section in terr_a
        sec = CanvassSection(territory_id=terr_a.id, name=f"S-{sfx}", geometry=SEC_A,
                             assigned_user_id=rep.id, active=True, created_by=owner.email)
        db.add(sec); await db.flush()

        # Visit on p_owner to test last_outcome/last_visited_at
        v_old = Visit(property_id=p_owner.id, user_id=rep.id, user_email=rep.email,
                      visited_at=datetime.now(timezone.utc) - timedelta(days=2), outcome="no_answer")
        v_new = Visit(property_id=p_owner.id, user_id=rep.id, user_email=rep.email,
                      visited_at=datetime.now(timezone.utc), outcome="not_interested")
        db.add_all([v_old, v_new])
        await db.commit()

        return {
            "owner": (str(owner.id), owner.email, "owner"),
            "rep": (str(rep.id), rep.email, "sales"),
            "rep_zero": (str(rep_zero.id), rep_zero.email, "sales"),
            "terr_a": str(terr_a.id), "terr_b": str(terr_b.id),
            "p_owner": str(p_owner.id), "p_tenant": str(p_tenant.id),
            "p_dnk": str(p_dnk.id), "p_nocoords": str(p_nocoords.id), "p_b": str(p_b.id),
            "sec": str(sec.id),
        }


def _tok(triple):
    from core import create_access_token
    uid, email, role = triple
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


S = None


def setup_module(_):
    global S
    S = run(_seed())


def _get(url, headers):
    r = requests.get(url, headers=headers, timeout=20)
    return r


# ---------- GET /api/mobile/map/properties ----------

def test_management_sees_full_authorized_map():
    r = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "FeatureCollection"
    ids = {f["properties"]["id"] for f in d["features"]}
    # All seeded WITH coords must be present; the no-coords one must be excluded.
    for k in ["p_owner", "p_tenant", "p_dnk", "p_b"]:
        assert S[k] in ids, f"expected {k} in management map"
    assert S["p_nocoords"] not in ids, "properties without coords must be excluded"


def test_sales_scoped_to_assigned_territories():
    r = _get(f"{API}/mobile/map/properties", _tok(S["rep"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "FeatureCollection"
    ids = {f["properties"]["id"] for f in d["features"]}
    # Rep is assigned a section in terr_a only -> sees terr_a props (with coords), not terr_b.
    assert S["p_owner"] in ids and S["p_tenant"] in ids and S["p_dnk"] in ids
    assert S["p_b"] not in ids, "sales must NOT see properties in unassigned territories"
    assert S["p_nocoords"] not in ids


def test_sales_zero_sections_gets_empty_feature_collection():
    r = _get(f"{API}/mobile/map/properties", _tok(S["rep_zero"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "FeatureCollection"
    assert d["features"] == [], "zero-section sales user must get empty features, not an error"


def test_feature_geometry_and_properties_shape():
    r = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    d = r.json()
    by_id = {f["properties"]["id"]: f for f in d["features"]}

    fo = by_id[S["p_owner"]]
    assert fo["type"] == "Feature"
    assert fo["geometry"]["type"] == "Point"
    lon, lat = fo["geometry"]["coordinates"]
    assert lon == 2.0 and lat == 2.0, "coordinates must be [lon, lat]"
    for key in ["id", "address", "property_type", "owner_occupied", "occupancy",
                "do_not_knock", "last_outcome", "last_visited_at"]:
        assert key in fo["properties"], f"missing property key: {key}"
    assert fo["properties"]["occupancy"] == "owner"
    assert fo["properties"]["owner_occupied"] is True
    assert fo["properties"]["do_not_knock"] is False
    # Latest visit wins.
    assert fo["properties"]["last_outcome"] == "not_interested"
    assert fo["properties"]["last_visited_at"] is not None

    ft = by_id[S["p_tenant"]]
    assert ft["properties"]["occupancy"] == "tenant"
    assert ft["properties"]["owner_occupied"] is False
    assert ft["properties"]["last_outcome"] is None
    assert ft["properties"]["last_visited_at"] is None

    fd = by_id[S["p_dnk"]]
    assert fd["properties"]["do_not_knock"] is True
    assert fd["properties"]["occupancy"] == "unknown"
    assert fd["properties"]["owner_occupied"] is None


def test_endpoint_requires_auth():
    r = requests.get(f"{API}/mobile/map/properties", timeout=20)
    assert r.status_code in (401, 403)


# ---------- Regression: canvass-section endpoints still enforce isolation ----------

# ---------- RT1–RT5 explicit permanent regression names ----------

def test_RT1_no_canvass_assignment_returns_populated_or_valid_empty_state():
    """RT1 (permanent): Sales user with ZERO canvass sections still gets a VALID FeatureCollection
    (empty features). The endpoint must NOT 403/500 and must return type=FeatureCollection so the
    client-side reducer keeps the master property dataset (offlineNoCache must remain false)."""
    r = _get(f"{API}/mobile/map/properties", _tok(S["rep_zero"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "FeatureCollection"
    assert isinstance(d["features"], list)
    assert d["features"] == []


def test_RT_authorization_map_endpoint_does_not_widen_scope():
    """Authorization contract: the map endpoint MUST NOT widen a Sales user's visibility beyond
    their authorized territories. Assertions:
      1. Every property returned by /mobile/map/properties (as sales) is in the seeded authorized
         territory (terr_a): the sales feature set is a subset of the management feature set,
         and equals the seeded terr_a subset.
      2. A property in a NON-authorized territory (terr_b) is NOT in the sales map AND is refused
         on GET /api/properties/{id} (no cross-territory ID leak).
    """
    r_rep = _get(f"{API}/mobile/map/properties", _tok(S["rep"]))
    assert r_rep.status_code == 200
    rep_ids = {f["properties"]["id"] for f in r_rep.json()["features"]}

    r_own = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    assert r_own.status_code == 200
    own_ids = {f["properties"]["id"] for f in r_own.json()["features"]}

    # (1) Sales set is a subset of management set — no elevation via the map endpoint.
    assert rep_ids.issubset(own_ids), "sales map must be a subset of management map"
    # And equals the seeded terr_a properties with coords (no cross-territory leak either way).
    expected_rep = {S["p_owner"], S["p_tenant"], S["p_dnk"]}
    assert rep_ids == expected_rep, (
        f"sales map must equal exactly the authorized terr_a props with coords; got {rep_ids}, "
        f"expected {expected_rep}")

    # (2) terr_b property must NOT be on the sales map AND detail must be forbidden.
    assert S["p_b"] not in rep_ids
    forbidden = _get(f"{API}/properties/{S['p_b']}", _tok(S["rep"]))
    assert forbidden.status_code in (403, 404), (
        f"cross-territory property detail must be forbidden; got {forbidden.status_code}")


def test_canvass_sections_isolation_regression():
    # rep_zero (sales, no sections) cannot access rep's section.
    r_forbidden = _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", _tok(S["rep_zero"]))
    assert r_forbidden.status_code == 403, r_forbidden.text
    # rep can.
    r_ok = _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", _tok(S["rep"]))
    assert r_ok.status_code == 200, r_ok.text
    body = r_ok.json()
    assert body["section_id"] == S["sec"]
    assert body["type"] == "FeatureCollection"
    # rep_zero listing has no sections; rep sees their section.
    r_list_zero = _get(f"{API}/mobile/canvass-sections", _tok(S["rep_zero"]))
    assert r_list_zero.status_code == 200
    assert S["sec"] not in [s["id"] for s in r_list_zero.json()["sections"]]
    r_list_rep = _get(f"{API}/mobile/canvass-sections", _tok(S["rep"]))
    assert S["sec"] in [s["id"] for s in r_list_rep.json()["sections"]]
