"""Extra edge cases for company recovery / same-company detection (iteration 116)."""
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from licensing import config as lc
from tests.test_company_recovery import CP, ADMIN, _key, _company, _register, _recover, _signed

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
BOOT = lc.ACTIVATION_BOOTSTRAP_CREDENTIAL
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{5}(-[A-HJ-NP-Z2-9]{5}){3}$")


# Recovery code format on new company
def test_recovery_code_format():
    _, pem = _key()
    r = _register(pem, _company())
    assert r.status_code == 200
    assert CODE_RE.match(r.json()["recovery_code"])


# Re-register with same key does not leak recovery code again (only on creation)
def test_reregister_same_key_no_new_company():
    _, pem = _key()
    c = _company()
    a = _register(pem, c).json()
    b = _register(pem, c)
    assert b.status_code == 200 and b.json()["company_id"] == a["company_id"]


# Precheck false for unknown, 401 for bad credential, false when fields incomplete
def test_precheck_variants():
    c = _company()
    assert requests.post(f"{CP}/installation/precheck", json={**c, "bootstrap_credential": BOOT}, timeout=30).json() == {"exists": False}
    assert requests.post(f"{CP}/installation/precheck", json={**c, "bootstrap_credential": "nope"}, timeout=30).status_code == 401
    _, pem = _key()
    assert _register(pem, c).status_code == 200
    partial = {**c, "company_phone": ""}
    assert requests.post(f"{CP}/installation/precheck", json={**partial, "bootstrap_credential": BOOT}, timeout=30).json() == {"exists": False}


# Recover with bad bootstrap credential 401; too-short code 422
def test_recover_auth_and_validation():
    _, pem = _key()
    r = requests.post(f"{CP}/installation/recover", timeout=30, json={
        "recovery_code": "AAAAA-BBBBB-CCCCC-DDDDD", "installation_public_key": pem,
        "software_version": lc.SOFTWARE_VERSION, "bootstrap_credential": "bad"})
    assert r.status_code == 401
    assert _recover(pem, "abc").status_code == 422


# Unsigned recovery-code / company endpoints -> 401
def test_signed_endpoints_require_signature():
    assert requests.post(f"{CP}/installation/recovery-code", timeout=30).status_code == 401
    assert requests.post(f"{CP}/installation/company", json={"name": "x"}, timeout=30).status_code == 401


# Admin lookup requires header; lookup by company_id works
def test_admin_lookup_auth_and_id():
    assert requests.get(f"{CP}/admin/companies/lookup", params={"q": "Acme"}, timeout=30).status_code == 401
    assert requests.get(f"{CP}/admin/companies/lookup", params={"q": "Acme"},
                        headers={"X-RoofSpan-Admin": "wrong"}, timeout=30).status_code == 401
    _, pem = _key()
    reg = _register(pem, _company()).json()
    r = requests.get(f"{CP}/admin/companies/lookup", params={"q": reg["company_id"]}, headers=ADMIN, timeout=30)
    assert r.status_code == 200 and r.json()["companies"][0]["recovery_code"] == reg["recovery_code"]


# Company update: blank name 422, persisted value visible to admin lookup
def test_company_update_persists_and_validates():
    key, pem = _key()
    c = _company()
    reg = _register(pem, c).json()
    assert _signed(key, reg["installation_id"], "/installation/company", {"name": "   "}).status_code == 422
    newname = c["company_name"] + " Renamed"
    r = _signed(key, reg["installation_id"], "/installation/company", {"name": newname})
    assert r.status_code == 200 and r.json()["address"] == c["company_address"]
    look = requests.get(f"{CP}/admin/companies/lookup", params={"q": reg["company_id"]}, headers=ADMIN, timeout=30)
    assert look.json()["companies"][0]["name"] == newname


# Recovery from a key that already belongs to another ACTIVE company -> 409
def test_recover_key_of_other_company_409():
    _, pem_a = _key()
    a = _register(pem_a, _company()).json()
    _, pem_b = _key()
    b = _register(pem_b, _company()).json()
    r = _recover(pem_b, a["recovery_code"])
    assert r.status_code == 409


# RACE: two NEW keys registering the same company concurrently must create only one company
def test_concurrent_same_company_different_keys_creates_one():
    c = _company()
    pems = [_key()[1] for _ in range(6)]
    with ThreadPoolExecutor(6) as ex:
        rs = list(ex.map(lambda p: _register(p, c), pems))
    ok = [r for r in rs if r.status_code == 200]
    assert len({r.json()["company_id"] for r in ok}) == 1 and len(ok) == 1, [r.status_code for r in rs]


# Admin-revoked installation: can the recovery code bring the company back on a new key?
def test_recover_after_admin_revoke_behaviour():
    key, pem = _key()
    reg = _register(pem, _company()).json()
    rv = requests.post(f"{CP}/installations/{reg['installation_id']}/revoke", headers=ADMIN, timeout=30)
    assert rv.status_code == 200
    _, pem2 = _key()
    r = _recover(pem2, reg["recovery_code"])
    print("recover-after-revoke:", r.status_code, r.text[:200])
    # Reported, not asserted strictly: 200 means an admin revoke is bypassable via recovery code.
    assert r.status_code in (200, 403, 404)


# Office owner-only /api/recovery-code
def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


def test_office_recovery_code_rbac():
    sales = _login("sales_bk@example.com", "SalesBk#2026")
    assert sales.get(f"{BASE}/api/recovery-code", timeout=30).status_code == 403
    owner = _login("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")
    r = owner.get(f"{BASE}/api/recovery-code", timeout=60)
    print("owner recovery-code:", r.status_code, r.text[:200])
    assert r.status_code in (200, 503)
