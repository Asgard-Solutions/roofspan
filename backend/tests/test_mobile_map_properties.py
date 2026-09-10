"""P0 regression coverage for the RoofSpan Field "My Area" map.

Phase 3 CONTRACT CHANGE (locked in permanently by these tests):

  GET /api/mobile/map/properties is the MASTER map-safe property dataset for the mobile Field
  UI. It is NOT gated by canvass/territory assignments. Every Field user (sales + management)
  receives the SAME FeatureCollection of all properties that have usable lat/long coordinates.
  Only map-safe fields are exposed on each feature (id, address, property_type, owner_occupied,
  occupancy, do_not_knock, last_outcome, last_visited_at). Properties without lat/long are
  excluded. Property-detail authorization is enforced SEPARATELY (GET /api/properties/{id})
  and is out of scope for this endpoint's contract.

Phase 2 CONTRACT (canvass section assignment; still sales-isolated):

  /api/mobile/canvass-sections and /api/mobile/canvass-sections/{id}/properties honor the
  server-authoritative `assigned_user_id` + `active` fields. A section assigned to user U is
  visible to U and forbidden to other sales users; reassignment moves visibility; deactivation
  removes visibility. The Phase-2 assertions here exercise the real login flow (/api/auth/login
  -> access_token -> authenticated GETs) to prove the `assigned_user_id <-> User.id` path
  through JWT and dependency resolution, not just an in-memory equality.
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

# Map-safe property fields exposed on the mobile master map. Nothing else should be present.
MAP_SAFE_KEYS = {"id", "address", "property_type", "owner_occupied", "occupancy",
                 "do_not_knock", "last_outcome", "last_visited_at"}
# Explicit deny-list: these fields (contacts/phones/notes/credentials/etc.) MUST NOT appear.
FORBIDDEN_KEYS = {"phone", "phones", "phone_number", "email", "notes", "note", "contacts",
                  "contact", "credentials", "password", "password_hash", "token",
                  "access_token", "refresh_token", "owner_email", "owner_name"}

PWD = "TestP@ss1"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _seed():
    from db import SessionLocal
    from models import User, Territory, Property, CanvassSection, Visit
    from core import hash_password
    async with SessionLocal() as db:
        sfx = uuid.uuid4().hex[:8]
        owner = User(email=f"mapown_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Own", role="owner")
        rep = User(email=f"maprep_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Rep A", role="sales")
        rep_zero = User(email=f"mapzero_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Rep Zero", role="sales")
        rep_other = User(email=f"mapother_{sfx}@t.io", password_hash=hash_password(PWD), full_name="Rep Other", role="sales")
        db.add_all([owner, rep, rep_zero, rep_other]); await db.flush()

        terr_a = Territory(name=f"MAP-A-{sfx}", geometry=TERR_A, created_by=owner.email)
        terr_b = Territory(name=f"MAP-B-{sfx}", geometry=TERR_B, created_by=owner.email)
        db.add_all([terr_a, terr_b]); await db.flush()

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
        p_b = Property(territory_id=terr_b.id, formatted_address=f"B-only-{sfx}",
                       latitude=25.0, longitude=25.0, do_not_knock=False)
        p_badcoords = Property(territory_id=terr_a.id, formatted_address=f"A-badcoords-{sfx}",
                               latitude=999.0, longitude=2.0, do_not_knock=False)
        db.add_all([p_owner, p_tenant, p_dnk, p_nocoords, p_b, p_badcoords]); await db.flush()

        sec = CanvassSection(territory_id=terr_a.id, name=f"S-{sfx}", geometry=SEC_A,
                             assigned_user_id=rep.id, active=True, created_by=owner.email)
        db.add(sec); await db.flush()

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
            "rep_other": (str(rep_other.id), rep_other.email, "sales"),
            "terr_a": str(terr_a.id), "terr_b": str(terr_b.id),
            "p_owner": str(p_owner.id), "p_tenant": str(p_tenant.id),
            "p_dnk": str(p_dnk.id), "p_nocoords": str(p_nocoords.id), "p_b": str(p_b.id),
            "p_badcoords": str(p_badcoords.id),
            "sec": str(sec.id),
        }


def _tok(triple):
    """Direct JWT (bypasses login) — used where the login path is not what's under test."""
    from core import create_access_token
    uid, email, role = triple
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


def _login_headers(email: str, password: str = PWD):
    """Real login flow — proves JWT + auth dependency resolves back to the user we seeded."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    j = r.json()
    tok = j["access_token"]
    assert isinstance(tok, str) and len(tok) > 0
    return {"Authorization": f"Bearer {tok}"}


S = None


def setup_module(_):
    global S
    S = run(_seed())


def _get(url, headers):
    return requests.get(url, headers=headers, timeout=20)


async def _reassign_section(section_id, new_user_id=None, active=None):
    """Use a FRESH async engine per call so each event loop owns its own pool
    (avoids 'attached to a different loop' when using asyncio.new_event_loop per call)."""
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import select
    from models import CanvassSection
    eng = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, echo=False)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            sec = (await db.execute(
                select(CanvassSection).where(CanvassSection.id == uuid.UUID(section_id))
            )).scalar_one()
            if new_user_id is not None:
                sec.assigned_user_id = uuid.UUID(new_user_id) if new_user_id else None
            if active is not None:
                sec.active = active
            await db.commit()
    finally:
        await eng.dispose()


# ================================================================================
# /api/mobile/map/properties CONTRACT — SCOPED to the selected area (territory/zip)
# Field never downloads the whole DB; scope is server-authoritative.
# ================================================================================

def test_management_territory_scoped_returns_only_that_territory():
    """Management passes ?territory_id → gets ONLY that territory's map-safe props (Office parity)."""
    r = _get(f"{API}/mobile/map/properties?territory_id={S['terr_a']}", _tok(S["owner"]))
    assert r.status_code == 200, r.text
    ids = {f["properties"]["id"] for f in r.json()["features"]}
    assert ids == {S["p_owner"], S["p_tenant"], S["p_dnk"]}, "territory A scope = exactly A's coord'd props"
    assert S["p_b"] not in ids, "territory B property must NOT appear in a territory A request"
    assert S["p_nocoords"] not in ids and S["p_badcoords"] not in ids, "no-coord/invalid-coord excluded"

    r_b = _get(f"{API}/mobile/map/properties?territory_id={S['terr_b']}", _tok(S["owner"]))
    ids_b = {f["properties"]["id"] for f in r_b.json()["features"]}
    assert ids_b == {S["p_b"]}, "territory B scope = exactly B's props"


def test_sales_scoped_to_assigned_territory_and_denied_others():
    """A sales rep with an active section in terr_a is scoped to terr_a and 403'd on terr_b."""
    r_a = _get(f"{API}/mobile/map/properties?territory_id={S['terr_a']}", _tok(S["rep"]))
    assert r_a.status_code == 200, r_a.text
    ids_a = {f["properties"]["id"] for f in r_a.json()["features"]}
    assert ids_a == {S["p_owner"], S["p_tenant"], S["p_dnk"]}, "rep sees exactly terr_a's props"
    assert S["p_b"] not in ids_a, "rep must not see terr_b property via terr_a request"

    # No-param request is ALSO scoped to the rep's authorized territory (never the whole DB).
    r_np = _get(f"{API}/mobile/map/properties", _tok(S["rep"]))
    ids_np = {f["properties"]["id"] for f in r_np.json()["features"]}
    assert S["p_b"] not in ids_np, "assigned rep's default map is scoped to their territory (no terr_b)"

    # A territory the rep is NOT authorized for → 403 (server-authoritative isolation).
    r_forbid = _get(f"{API}/mobile/map/properties?territory_id={S['terr_b']}", _tok(S["rep"]))
    assert r_forbid.status_code == 403, "rep must be denied a territory outside their scope"


def test_field_office_territory_property_parity():
    """For the SAME territory, Field's scoped property IDs match Office's canonical /properties/geojson
    IDs — Field and Office agree on territory membership + coordinates."""
    r_field = _get(f"{API}/mobile/map/properties?territory_id={S['terr_a']}", _tok(S["owner"]))
    r_office = _get(f"{API}/properties/geojson?territory_id={S['terr_a']}", _tok(S["owner"]))
    assert r_field.status_code == 200 and r_office.status_code == 200
    field_ids = {f["properties"]["id"] for f in r_field.json()["features"]}
    office_ids = {f["properties"]["id"] for f in r_office.json()["features"]}
    # Field applies an extra coordinate-range safety filter (Office's geojson does not), so the ONLY
    # allowed difference is the intentionally-invalid-coordinate property. Every valid property matches.
    assert S["p_badcoords"] in office_ids, "Office geojson does not range-validate (includes bad coords)"
    assert field_ids == office_ids - {S["p_badcoords"]}, \
        "Field territory property IDs match Office's for the same territory (minus invalid-coord safety)"
    # Coordinates identical + [lon, lat] order.
    fo = next(f for f in r_field.json()["features"] if f["properties"]["id"] == S["p_owner"])
    assert fo["geometry"]["coordinates"] == [2.0, 2.0], "coordinates are [lon, lat], same stored values as Office"


def test_invalid_coordinates_excluded():
    """A property with out-of-range coordinates (lat 999) is NEVER placed on the map."""
    r = _get(f"{API}/mobile/map/properties?territory_id={S['terr_a']}", _tok(S["owner"]))
    ids = {f["properties"]["id"] for f in r.json()["features"]}
    assert S["p_badcoords"] not in ids, "invalid-coordinate property must be excluded (no fake pin)"


def test_map_safe_fields_only_no_secrets_or_contacts():
    """Feature.properties exposes ONLY map-safe fields. No contacts/phones/notes/credentials."""
    r = _get(f"{API}/mobile/map/properties?territory_id={S['terr_a']}", _tok(S["owner"]))
    d = r.json()
    by_id = {f["properties"]["id"]: f for f in d["features"]}
    fo = by_id[S["p_owner"]]
    assert fo["type"] == "Feature" and fo["geometry"]["type"] == "Point"
    lon, lat = fo["geometry"]["coordinates"]
    assert lon == 2.0 and lat == 2.0, "coordinates must be [lon, lat]"
    props_keys = set(fo["properties"].keys())
    missing = MAP_SAFE_KEYS - props_keys
    assert not missing, f"missing map-safe keys: {missing}"
    leaked = FORBIDDEN_KEYS & props_keys
    assert not leaked, f"forbidden fields leaked on map feature: {leaked}"
    assert fo["properties"]["occupancy"] == "owner"
    assert fo["properties"]["owner_occupied"] is True
    assert fo["properties"]["do_not_knock"] is False
    assert fo["properties"]["last_outcome"] == "not_interested"  # latest visit wins
    assert fo["properties"]["last_visited_at"] is not None

    ft = by_id[S["p_tenant"]]
    assert ft["properties"]["occupancy"] == "tenant"
    assert ft["properties"]["last_outcome"] is None
    assert ft["properties"]["last_visited_at"] is None

    fd = by_id[S["p_dnk"]]
    assert fd["properties"]["do_not_knock"] is True
    assert fd["properties"]["occupancy"] == "unknown"


def test_phase3_endpoint_requires_auth():
    r = requests.get(f"{API}/mobile/map/properties", timeout=20)
    assert r.status_code in (401, 403)


# ================================================================================
# PHASE 2 — Canvass section assignment lifecycle (via REAL login flow)
# ================================================================================

def test_phase2_login_flow_returns_assigned_section_only_for_owner():
    """Real login: /api/auth/login -> access_token -> /api/mobile/canvass-sections.
    Proves the assigned_user_id <-> authenticated User.id path through JWT + auth dep."""
    _, rep_email, _ = S["rep"]
    _, other_email, _ = S["rep_other"]
    rep_h = _login_headers(rep_email)
    other_h = _login_headers(other_email)

    r_rep = _get(f"{API}/mobile/canvass-sections", rep_h)
    r_other = _get(f"{API}/mobile/canvass-sections", other_h)
    assert r_rep.status_code == 200 and r_other.status_code == 200
    rep_ids = [s["id"] for s in r_rep.json()["sections"]]
    other_ids = [s["id"] for s in r_other.json()["sections"]]
    assert S["sec"] in rep_ids, "rep (assignee) must receive their section via real login flow"
    assert S["sec"] not in other_ids, "a DIFFERENT sales user must NOT receive the section"

    # Section-detail endpoint enforces the same isolation.
    r_ok = _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", rep_h)
    r_forbid = _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", other_h)
    assert r_ok.status_code == 200
    assert r_forbid.status_code == 403


def test_phase2_reassignment_moves_visibility_and_deactivation_removes_it():
    """Reassign S from rep -> rep_other, then deactivate. Prove that visibility follows the
    server-authoritative assigned_user_id + active flags."""
    _, rep_email, _ = S["rep"]
    _, other_email, _ = S["rep_other"]

    # Reassign S -> rep_other.
    run(_reassign_section(S["sec"], new_user_id=S["rep_other"][0]))
    rep_h = _login_headers(rep_email)
    other_h = _login_headers(other_email)
    r_rep = _get(f"{API}/mobile/canvass-sections", rep_h)
    r_other = _get(f"{API}/mobile/canvass-sections", other_h)
    assert S["sec"] not in [s["id"] for s in r_rep.json()["sections"]], \
        "after reassignment, previous assignee must NOT see the section"
    assert S["sec"] in [s["id"] for s in r_other.json()["sections"]], \
        "after reassignment, new assignee MUST see the section"
    # Section-detail authorization tracks the assignment.
    assert _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", rep_h).status_code == 403
    assert _get(f"{API}/mobile/canvass-sections/{S['sec']}/properties", other_h).status_code == 200

    # Deactivate the section — even the new assignee no longer sees it.
    run(_reassign_section(S["sec"], active=False))
    r_other2 = _get(f"{API}/mobile/canvass-sections", other_h)
    assert S["sec"] not in [s["id"] for s in r_other2.json()["sections"]], \
        "inactive section must be excluded from the assignee's list"

    # Restore state for other test modules / re-runs.
    run(_reassign_section(S["sec"], new_user_id=S["rep"][0], active=True))


def test_phase2_map_endpoint_still_canvass_independent_after_deactivation():
    """After all sections for rep are deactivated, rep STILL gets the full master map.
    (The Phase-3 fix's core promise: canvass state cannot empty the map.)"""
    run(_reassign_section(S["sec"], active=False))
    try:
        _, rep_email, _ = S["rep"]
        rep_h = _login_headers(rep_email)
        # Canvass list is empty.
        r_sections = _get(f"{API}/mobile/canvass-sections", rep_h)
        assert r_sections.status_code == 200
        assert S["sec"] not in [s["id"] for s in r_sections.json()["sections"]]
        # But the master map is still fully populated.
        r_map = _get(f"{API}/mobile/map/properties", rep_h)
        assert r_map.status_code == 200
        ids = {f["properties"]["id"] for f in r_map.json()["features"]}
        for k in ["p_owner", "p_tenant", "p_dnk", "p_b"]:
            assert S[k] in ids, f"map must remain populated with {k} despite zero active sections"
    finally:
        run(_reassign_section(S["sec"], active=True))
