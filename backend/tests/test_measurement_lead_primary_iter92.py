"""Iter 92: Canonical measurement-set migration correctness.

Covers:
  - UNIQUE constraint uq_measurement_revisions_set_number exists and is enforced.
  - Revision numbering after normal use is unique + deterministic (matches created_at order).
  - Lead-primary resolution: distinct leads never inherit another lead's measurement set.
  - Regression: measurement lifecycle (POST 201, PUT If-Match 200, stale 409 with server detail, invalid 422).
  - Office (GET /api/measurements) vs Field (GET /api/mobile/measurements) return same revision family.
  - Migration report line present in migration file.
"""
import os
import re
import uuid
import time
import psycopg2
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"

# --- DB connection (convert asyncpg URL to sync psycopg2) ---
_DB_URL_RAW = None
with open("/app/backend/.env") as f:
    for ln in f:
        if ln.startswith("DATABASE_URL"):
            _DB_URL_RAW = ln.split("=", 1)[1].strip().strip('"').strip("'")
            break
assert _DB_URL_RAW, "DATABASE_URL missing"
_DB_URL_SYNC = _DB_URL_RAW.replace("postgresql+asyncpg://", "postgresql://")


def _db():
    return psycopg2.connect(_DB_URL_SYNC)


# ---------------- auth / helpers ----------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _mk_property(h):
    r = requests.post(f"{BASE_URL}/api/properties", headers=h,
                      json={"address": f"TEST_iter92 {uuid.uuid4().hex[:8]}",
                            "city": "Denver", "state": "CO", "zip_code": "80202"}, timeout=30)
    assert r.status_code in (200, 201), f"prop: {r.status_code} {r.text}"
    d = r.json()
    return d.get("id") or d.get("property_id")


def _mk_lead(h, property_id, name=None):
    r = requests.post(f"{BASE_URL}/api/mobile/leads", headers=h,
                      json={"name": name or f"TEST_lead_{uuid.uuid4().hex[:6]}",
                            "property_id": property_id}, timeout=30)
    assert r.status_code in (200, 201), f"lead: {r.status_code} {r.text}"
    d = r.json()
    return d["id"], d


def _post_measurement(h, lead_id, **extra):
    body = {"lead_id": lead_id, "source": "field",
            "structures": [{"name": "A", "structure_type": "main_house"}],
            "facets": [], "edges": [], "penetrations": [], "summary": {}}
    body.update(extra)
    return requests.post(f"{BASE_URL}/api/mobile/measurements",
                         headers={**h, "Idempotency-Key": uuid.uuid4().hex},
                         json=body, timeout=30)


# ---------------- 1) UNIQUE constraint exists and is enforced ----------------
def test_unique_constraint_exists_in_pg_constraint():
    with _db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT conname, contype FROM pg_constraint
                       WHERE conname = 'uq_measurement_revisions_set_number'""")
        row = cur.fetchone()
    assert row is not None, "uq_measurement_revisions_set_number is missing"
    assert row[1] == "u", f"expected UNIQUE (u), got {row[1]}"


def test_unique_constraint_enforced_on_duplicate_insert(h):
    """Real integrity: try to duplicate an existing revision_number inside one set."""
    prop = _mk_property(h)
    lead_id, _ = _mk_lead(h, prop)
    r = _post_measurement(h, lead_id)
    assert r.status_code == 201, r.text
    rev = r.json()
    rev_id = rev.get("id") or rev.get("revision_id")

    with _db() as conn, conn.cursor() as cur:
        cur.execute("SELECT set_id, revision_number FROM measurement_revisions WHERE id = %s", (rev_id,))
        set_id, rev_num = cur.fetchone()

    # Attempt a duplicate (set_id, revision_number) insert — must raise IntegrityError.
    dup_id = str(uuid.uuid4())
    raised = False
    try:
        with _db() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO measurement_revisions
                   (id, set_id, revision_number, status, created_at, updated_at)
                   VALUES (%s, %s, %s, 'draft', now(), now())""",
                (dup_id, set_id, rev_num),
            )
            conn.commit()
    except psycopg2.errors.UniqueViolation:
        raised = True
    except psycopg2.Error as e:
        # Some columns may be NOT NULL and fail first; retry with a broader insert only if that happens.
        if "uq_measurement_revisions_set_number" in str(e):
            raised = True
        else:
            # Try to determine required cols dynamically and retry
            with _db() as conn, conn.cursor() as cur:
                cur.execute("""SELECT column_name FROM information_schema.columns
                               WHERE table_name='measurement_revisions' AND is_nullable='NO'
                                 AND column_default IS NULL""")
                required = [r[0] for r in cur.fetchall()]
            # Build minimal insert with NULL-safe defaults where possible
            print(f"required NOT NULL cols with no default: {required}; original error: {e}")
            raise
    assert raised, "Duplicate (set_id, revision_number) insert should have been blocked by UNIQUE constraint"


# ---------------- 2) Revision numbering deterministic & unique after normal use ----------------
def test_revision_numbers_unique_and_ordered_matches_created_at(h):
    prop = _mk_property(h)
    lead_id, _ = _mk_lead(h, prop)
    r = _post_measurement(h, lead_id)
    assert r.status_code == 201, r.text
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")
    updated_at = m["updated_at"]

    # Several PUTs — each creates a new revision if the endpoint rotates revisions;
    # otherwise updated_at rotates in-place. Either way, revision_numbers must remain unique.
    for i in range(3):
        put = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                           headers={**h, "If-Match": updated_at},
                           json={"structures": [{"name": f"S{i}", "structure_type": "main_house"}]},
                           timeout=30)
        assert put.status_code == 200, f"put {i}: {put.status_code} {put.text}"
        updated_at = put.json()["updated_at"]
        # ensure created_at ordering doesn't tie
        time.sleep(0.05)

    # Additionally force new revisions via office /new-revision (if available) for stronger coverage.
    for _ in range(2):
        nr = requests.post(f"{BASE_URL}/api/measurements/{rev_id}/new-revision", headers=h, timeout=30)
        if nr.status_code == 201:
            rev_id = nr.json().get("id") or nr.json().get("revision_id") or rev_id

    lst = requests.get(f"{BASE_URL}/api/mobile/measurements", headers=h,
                       params={"lead_id": lead_id}, timeout=30)
    assert lst.status_code == 200, lst.text
    items = lst.json()
    assert isinstance(items, list) and len(items) >= 1
    nums = [x.get("revision_number") for x in items]
    assert len(nums) == len(set(nums)), f"revision numbers not unique: {nums}"
    # Compare against DB ordering by created_at ASC
    with _db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT r.revision_number FROM measurement_revisions r
                       JOIN measurement_sets s ON s.id = r.set_id
                       WHERE s.lead_id = %s
                       ORDER BY r.created_at ASC, r.id ASC""", (lead_id,))
        db_nums_asc = [r[0] for r in cur.fetchall()]
    assert db_nums_asc == sorted(db_nums_asc), \
        f"revision_number not monotonic by created_at: {db_nums_asc}"
    assert db_nums_asc == list(range(1, len(db_nums_asc) + 1)), \
        f"revision_number should be 1..N in chronological order, got {db_nums_asc}"


# ---------------- 3) Lead-primary resolution ----------------
def test_lead_primary_key_resolution(h):
    prop = _mk_property(h)
    leadA, _ = _mk_lead(h, prop, name=f"TEST_A_{uuid.uuid4().hex[:6]}")
    leadB, _ = _mk_lead(h, prop, name=f"TEST_B_{uuid.uuid4().hex[:6]}")
    print(f"leadA={leadA} leadB={leadB} property={prop}")

    # Measurement for lead A only
    r = _post_measurement(h, leadA)
    assert r.status_code == 201, r.text
    a_rev = r.json()
    a_set_id = None
    # Ask watermark for A — must return a non-null set
    wa = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=h,
                      params={"lead_id": leadA}, timeout=30)
    assert wa.status_code == 200, wa.text
    a_wm = wa.json()
    assert a_wm.get("measurement_set_id"), f"lead A must have a set: {a_wm}"
    a_set_id = a_wm["measurement_set_id"]
    assert a_wm.get("revisions"), "lead A must have revisions"

    if leadA == leadB:
        # API deduped — cannot execute distinct-leads-same-property scenario; fall back.
        pytest.skip("POST /api/mobile/leads deduped leads by property; distinct-leads test bypassed. "
                    "Fallback test_lead_primary_two_properties covers resolution correctness.")

    # Watermark for B — MUST be empty (different lead, even though shared property)
    wb = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=h,
                     params={"lead_id": leadB}, timeout=30)
    assert wb.status_code == 200, wb.text
    b_wm = wb.json()
    assert b_wm.get("measurement_set_id") in (None, ""), (
        f"BUG: lead B (id={leadB}) resolved to lead A's set. "
        f"A_set={a_set_id} B_watermark={b_wm}"
    )
    assert not b_wm.get("revisions"), f"lead B must have no revisions: {b_wm}"

    # List for B — must be empty
    lb = requests.get(f"{BASE_URL}/api/mobile/measurements", headers=h,
                      params={"lead_id": leadB}, timeout=30)
    assert lb.status_code == 200, lb.text
    assert lb.json() == [], f"lead B list must be empty: {lb.json()}"


def test_lead_primary_two_properties(h):
    """Fallback / additional: two distinct leads on DIFFERENT properties must have disjoint sets."""
    p1 = _mk_property(h)
    p2 = _mk_property(h)
    l1, _ = _mk_lead(h, p1)
    l2, _ = _mk_lead(h, p2)
    r1 = _post_measurement(h, l1)
    r2 = _post_measurement(h, l2)
    assert r1.status_code == 201
    assert r2.status_code == 201
    w1 = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=h,
                      params={"lead_id": l1}, timeout=30).json()
    w2 = requests.get(f"{BASE_URL}/api/mobile/measurements/watermark", headers=h,
                      params={"lead_id": l2}, timeout=30).json()
    assert w1["measurement_set_id"] and w2["measurement_set_id"]
    assert w1["measurement_set_id"] != w2["measurement_set_id"], "distinct leads must map to distinct sets"


# ---------------- 4) Regression: lifecycle + Office/Field parity ----------------
def test_office_field_parity_same_revision_family(h):
    prop = _mk_property(h)
    lead_id, _ = _mk_lead(h, prop)
    r = _post_measurement(h, lead_id)
    assert r.status_code == 201, r.text

    field = requests.get(f"{BASE_URL}/api/mobile/measurements", headers=h,
                         params={"lead_id": lead_id}, timeout=30)
    office = requests.get(f"{BASE_URL}/api/measurements", headers=h,
                          params={"lead_id": lead_id}, timeout=30)
    assert field.status_code == 200 and office.status_code == 200, (field.text, office.text)
    field_ids = sorted([x.get("id") or x.get("revision_id") for x in field.json()])
    office_ids = sorted([x.get("id") or x.get("revision_id") for x in office.json()])
    assert field_ids == office_ids, f"office vs field mismatch: office={office_ids} field={field_ids}"


def test_regression_stale_ifmatch_409_with_server_detail(h):
    prop = _mk_property(h)
    lead_id, _ = _mk_lead(h, prop)
    r = _post_measurement(h, lead_id)
    assert r.status_code == 201, r.text
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")
    rs = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                      headers={**h, "If-Match": "1970-01-01T00:00:00Z"},
                      json={"structures": [{"name": "X", "structure_type": "main_house"}]},
                      timeout=30)
    assert rs.status_code == 409, rs.text
    body = rs.json()
    detail = body.get("detail")
    assert isinstance(detail, dict), f"detail must be dict: {body}"
    assert "server" in detail, f"detail.server missing: {detail}"


def test_regression_invalid_body_422(h):
    prop = _mk_property(h)
    lead_id, _ = _mk_lead(h, prop)
    r = _post_measurement(h, lead_id)
    m = r.json()
    rev_id = m.get("id") or m.get("revision_id")
    updated_at = m["updated_at"]
    rb = requests.put(f"{BASE_URL}/api/mobile/measurements/{rev_id}",
                      headers={**h, "If-Match": updated_at},
                      json={"structures": "not-a-list"}, timeout=30)
    assert rb.status_code == 422, rb.text


# ---------------- 5) Migration report line present ----------------
def test_migration_prints_report_line():
    path = "/app/backend/alembic/versions/c4d5e6f7a8b9_revision_number_unique.py"
    with open(path) as f:
        src = f.read()
    assert "sets_fixed=" in src
    assert "revisions_renumbered=" in src
    assert "remaining_lead_relationship_conflicts=" in src
    # Ensure a print() actually emits it
    assert re.search(r"print\(\s*[\s\S]*?sets_fixed=", src), "migration must print the report"
