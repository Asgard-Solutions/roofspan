"""RC review (iteration 143): version endpoint, Office/Field gate, relay marker, legacy status mapping.
Creates one TEST_ lead and hard-deletes it by id at teardown (psql, by id only)."""
import os
import subprocess
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
NEW = {"X-RoofSpan-App-Version": "1.1.0"}
CREATED = []


def _db_url():
    for line in open("/app/backend/.env"):
        if line.startswith("DATABASE_URL"):
            return line.split("=", 1)[1].strip().strip('"').replace("+asyncpg", "")


def _psql(sql):
    return subprocess.run(["psql", _db_url(), "-tAc", sql], capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    if r.status_code != 200:
        pytest.skip("login failed")
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    for lid in CREATED:
        for t in ("audit_logs", "follow_ups"):
            pass
        out = subprocess.run(["psql", _db_url(), "-c", f"DELETE FROM leads WHERE id='{lid}'"], capture_output=True, text=True)
        print("cleanup", lid, out.stdout, out.stderr)


# Version
def test_version():
    v = requests.get(f"{API}/version", timeout=20).json()
    assert v["version"] == "0.5.0" and v["display_version"] == "0.5.0-dev"


# Gate: version header matrix
def test_gate_matrix(h):
    assert requests.get(f"{API}/mobile/leads", headers={**h, **NEW}, timeout=20).status_code == 200
    r = requests.get(f"{API}/mobile/leads", headers={**h, "X-RoofSpan-App-Version": "1.0.0"}, timeout=20)
    assert r.status_code == 426
    d = r.json()["detail"]
    assert d["code"] == "must_update" and d["app"] == "field" and d["min_supported"] == "1.1.0"
    # newer / malformed versions
    assert requests.get(f"{API}/mobile/leads", headers={**h, "X-RoofSpan-App-Version": "1.2.0"}, timeout=20).status_code == 200
    assert requests.get(f"{API}/mobile/leads", headers={**h, "X-RoofSpan-App-Version": "1.0.9"}, timeout=20).status_code == 426
    # gate runs before auth? unauthenticated old client
    r2 = requests.get(f"{API}/mobile/leads", headers={"X-RoofSpan-App-Version": "1.0.0"}, timeout=20)
    print("unauth old client:", r2.status_code)


# Relay marker without version => Field 1.0
def test_relayed_no_version(h):
    before = _psql("select count(*) from leads")
    rel = {**h, "X-RoofSpan-Relay-Forwarded": "1"}
    assert requests.get(f"{API}/mobile/leads", headers=rel, timeout=20).status_code == 426
    name = f"TEST_relay_{uuid.uuid4().hex[:6]}"
    w = requests.post(f"{API}/mobile/leads", headers=rel, json={"name": name}, timeout=20)
    assert w.status_code == 426
    assert _psql(f"select count(*) from leads where name='{name}'") == "0"
    assert _psql("select count(*) from leads") == before
    p = requests.get(f"{API}/mobile/photos/{uuid.uuid4()}/content", headers=rel, timeout=20)
    print("photo content relayed:", p.status_code, p.text[:120])
    assert p.status_code != 426


# Office web unaffected
def test_office_web(h):
    r = requests.get(f"{API}/mobile/leads", headers=h, timeout=20)
    assert r.status_code == 200
    data = r.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("leads") or []
    lid = items[0]["id"] if items else _psql("select id from leads limit 1")
    p = requests.get(f"{API}/mobile/photos", params={"record_type": "lead", "record_id": lid}, headers=h, timeout=20)
    assert p.status_code == 200, p.text


# Legacy status mapping
def test_legacy_status(h):
    hh = {**h, **NEW}
    c = requests.post(f"{API}/mobile/leads", headers=hh, json={"name": f"TEST_rc_{uuid.uuid4().hex[:6]}"}, timeout=20)
    assert c.status_code == 201, c.text
    lid = c.json()["id"]
    CREATED.append(lid)
    u = requests.patch(f"{API}/mobile/leads/{lid}", headers=hh, json={"status": "interested"}, timeout=20)
    assert u.status_code == 200 and u.json()["status"] == "qualified", u.text
    assert _psql(f"select status from leads where id='{lid}'") == "qualified"
    for bad in ("bogus", "converted"):
        b = requests.patch(f"{API}/mobile/leads/{lid}", headers=hh, json={"status": bad}, timeout=20)
        assert b.status_code == 422, (bad, b.status_code, b.text)
    o = requests.patch(f"{API}/leads/{lid}", headers=h, json={"status": "interested"}, timeout=20)
    assert o.status_code == 422, o.text
    assert _psql(f"select status from leads where id='{lid}'") == "qualified"
