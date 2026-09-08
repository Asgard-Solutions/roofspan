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
        db.add_all([p_owner, p_tenant, p_dnk, p_nocoords, p_b]); await db.flush()

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
# PHASE 3 — /api/mobile/map/properties CONTRACT (canvass-INDEPENDENT master map)
# ================================================================================

def test_phase3_management_gets_full_map_safe_dataset():
    """Management sees every property with valid coords; excludes those without lat/long."""
    r = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["type"] == "FeatureCollection"
    ids = {f["properties"]["id"] for f in d["features"]}
    for k in ["p_owner", "p_tenant", "p_dnk", "p_b"]:
        assert S[k] in ids, f"management must see {k}"
    assert S["p_nocoords"] not in ids, "properties without coords must be excluded"


def test_phase3_sales_map_equals_management_map():
    """CONTRACT CHANGE: master map is NOT territory/canvass-gated. A sales user sees the SAME
    set of features as a management user (map-safe only; detail authorization is separate)."""
    r_rep = _get(f"{API}/mobile/map/properties", _tok(S["rep"]))
    r_own = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    assert r_rep.status_code == 200 and r_own.status_code == 200
    rep_ids = {f["properties"]["id"] for f in r_rep.json()["features"]}
    own_ids = {f["properties"]["id"] for f in r_own.json()["features"]}
    assert rep_ids == own_ids, "sales map MUST equal management map (map is canvass-independent)"
    # Both terr_a and terr_b properties are on the sales map.
    assert S["p_owner"] in rep_ids and S["p_b"] in rep_ids
    assert S["p_nocoords"] not in rep_ids


def test_phase3_sales_with_zero_sections_gets_full_populated_map():
    """CONTRACT CHANGE (previously asserted empty): a sales user with ZERO assigned canvass
    sections STILL receives the full populated master property FeatureCollection."""
    r_zero = _get(f"{API}/mobile/map/properties", _tok(S["rep_zero"]))
    r_own = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    assert r_zero.status_code == 200, r_zero.text
    d = r_zero.json()
    assert d["type"] == "FeatureCollection"
    zero_ids = {f["properties"]["id"] for f in d["features"]}
    own_ids = {f["properties"]["id"] for f in r_own.json()["features"]}
    # Full map, NOT empty.
    assert len(zero_ids) > 0, "zero-section sales must receive the full populated map, not empty"
    assert zero_ids == own_ids, "zero-section sales map MUST equal management map"
    for k in ["p_owner", "p_tenant", "p_dnk", "p_b"]:
        assert S[k] in zero_ids


def test_phase3_map_safe_fields_only_no_secrets_or_contacts():
    """Feature.properties exposes ONLY map-safe fields. No contacts/phones/notes/credentials."""
    r = _get(f"{API}/mobile/map/properties", _tok(S["owner"]))
    d = r.json()
    by_id = {f["properties"]["id"]: f for f in d["features"]}
    fo = by_id[S["p_owner"]]
    assert fo["type"] == "Feature" and fo["geometry"]["type"] == "Point"
    lon, lat = fo["geometry"]["coordinates"]
    assert lon == 2.0 and lat == 2.0, "coordinates must be [lon, lat]"
    props_keys = set(fo["properties"].keys())
    # Every required map-safe key is present.
    missing = MAP_SAFE_KEYS - props_keys
    assert not missing, f"missing map-safe keys: {missing}"
    # No forbidden keys leaked.
    leaked = FORBIDDEN_KEYS & props_keys
    assert not leaked, f"forbidden fields leaked on map feature: {leaked}"
    # Business shape.
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
