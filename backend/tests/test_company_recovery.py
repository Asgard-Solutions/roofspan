"""Company recovery codes, same-company detection and one ACTIVE installation per identity (live API + DB)."""
import asyncio
import json
import os
import time
import uuid

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import config as lc
from licensing import reqsig

CP = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api/control-plane"
ADMIN = {"X-RoofSpan-Admin": os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")}


def _key():
    k = Ed25519PrivateKey.generate()
    pem = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return k, pem


def _company():
    tag = uuid.uuid4().hex[:8]
    return {"company_name": f"Acme Roofing {tag}", "company_phone": f"(512) 555-{int(tag[:4], 16) % 10000:04d}",
            "company_address": f"{tag} Main Street, Austin TX"}


def _register(pem, company):
    return requests.post(f"{CP}/installation/register", timeout=30, json={
        **company, "requested_seats": 5, "installation_public_key": pem, "software_version": lc.SOFTWARE_VERSION,
        "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL})


def _recover(pem, code):
    return requests.post(f"{CP}/installation/recover", timeout=30, json={
        "recovery_code": code, "installation_public_key": pem, "software_version": lc.SOFTWARE_VERSION,
        "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL})


def _signed(key, iid, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    sig = reqsig.sign_request(key, installation_id=iid, timestamp=ts, nonce=nonce, body=body)
    return requests.post(f"{CP}{path}", data=body, timeout=30, headers={
        reqsig.H_INSTALLATION: iid, reqsig.H_TIMESTAMP: ts, reqsig.H_NONCE: nonce, reqsig.H_SIGNATURE: sig,
        "content-type": "application/json"})


@pytest.fixture
def office():
    key, pem = _key()
    company = _company()
    r = _register(pem, company)
    assert r.status_code == 200, r.text
    return key, pem, company, r.json()


def test_new_company_gets_a_recovery_code_readable_by_office_and_staff(office):
    key, _, company, reg = office
    code = reg["recovery_code"]
    assert code and len(code.replace("-", "")) == 20
    assert _signed(key, reg["installation_id"], "/installation/recovery-code").json()["recovery_code"] == code
    found = requests.get(f"{CP}/admin/companies/lookup", params={"q": company["company_name"]}, headers=ADMIN, timeout=30)
    assert found.status_code == 200
    assert [c["recovery_code"] for c in found.json()["companies"]] == [code]


def test_same_name_phone_address_on_a_new_pc_is_stopped(office):
    _, _, company, _ = office
    precheck = requests.post(f"{CP}/installation/precheck", timeout=30,
                             json={**company, "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL})
    assert precheck.json() == {"exists": True}
    _, pem2 = _key()
    variant = {**company, "company_name": company["company_name"].upper() + "  ",
               "company_phone": company["company_phone"].replace("(", "").replace(")", "")}
    r = _register(pem2, variant)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "company_exists"


def test_same_name_but_different_phone_or_address_is_a_different_company(office):
    _, _, company, reg = office
    _, pem2 = _key()
    r = _register(pem2, {**company, "company_address": "999 Other Road, Dallas TX"})
    assert r.status_code == 200 and r.json()["company_id"] != reg["company_id"]


def test_recovery_moves_the_company_to_the_new_pc_and_disconnects_the_old_one(office):
    old_key, _, company, reg = office
    new_key, new_pem = _key()
    assert _recover(new_pem, "AAAAA-BBBBB-CCCCC-DDDDD").status_code == 404
    r = _recover(new_pem, reg["recovery_code"].lower().replace("-", " "))
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["company_id"] == reg["company_id"] and rec["installation_id"] != reg["installation_id"]
    assert rec["company_name"] == company["company_name"] and rec["company_address"] == company["company_address"]
    assert _signed(old_key, reg["installation_id"], "/installation/status").status_code == 403  # old PC is out
    assert _signed(new_key, rec["installation_id"], "/installation/status").status_code == 200
    again = _recover(new_pem, reg["recovery_code"])  # retry is idempotent
    assert again.status_code == 200 and again.json()["installation_id"] == rec["installation_id"]


def test_company_details_sync_updates_matching(office):
    key, _, company, reg = office
    r = _signed(key, reg["installation_id"], "/installation/company",
                {"name": company["company_name"], "phone": "(737) 555-0101", "address": company["company_address"]})
    assert r.status_code == 200 and r.json()["phone"] == "(737) 555-0101"
    pre = requests.post(f"{CP}/installation/precheck", timeout=30, json={
        **company, "company_phone": "737-555-0101", "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL})
    assert pre.json() == {"exists": True}


def test_database_refuses_a_second_active_row_for_the_same_identity(office):
    from sqlalchemy.exc import IntegrityError
    from control_plane.db import SessionLocal
    from control_plane.models import Installation
    _, pem, _, reg = office

    async def _dup():
        async with SessionLocal() as db:
            db.add(Installation(company_id=uuid.UUID(reg["company_id"]), public_key_pem=pem, status="ACTIVE",
                                software_version="x"))
            await db.commit()

    with pytest.raises(IntegrityError):
        asyncio.run(_dup())


def test_setup_restore_endpoints_are_closed_once_the_office_has_users():
    base = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api/setup/recover"
    assert requests.post(f"{base}/verify", json={"recovery_code": "AAAAA-BBBBB-CCCCC-DDDDD"}, timeout=30).status_code == 409
    assert requests.post(f"{base}/backups", json={"folder": "/tmp"}, timeout=30).status_code == 409
    assert requests.post(f"{base}/restore-folder", json={"folder": "/tmp", "filename": "roofspan_x.dump"},
                         timeout=30).status_code == 409
