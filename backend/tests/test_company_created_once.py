"""A company is created on the Control Plane exactly once per Office installation identity (live API)."""
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import config as lc

CP = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api/control-plane"


def _pem():
    k = Ed25519PrivateKey.generate()
    return k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def _body(pem):
    return {"company_name": "Acme Roofing Company", "requested_seats": 5, "installation_public_key": pem,
            "software_version": lc.SOFTWARE_VERSION, "bootstrap_credential": lc.ACTIVATION_BOOTSTRAP_CREDENTIAL}


def test_retries_and_both_endpoints_reuse_one_company():
    pem = _pem()
    ids = {requests.post(f"{CP}{p}", json=_body(pem), timeout=30).json()["company_id"]
           for p in ("/activate", "/installation/register", "/activate", "/installation/register")}
    assert len(ids) == 1


def test_concurrent_first_registration_creates_one_company():
    pem = _pem()
    paths = ["/activate", "/installation/register"] * 4
    with ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda p: requests.post(f"{CP}{p}", json=_body(pem), timeout=60), paths))
    assert all(r.status_code == 200 for r in rs)
    assert len({r.json()["company_id"] for r in rs}) == 1


def test_different_offices_are_different_companies():
    a = requests.post(f"{CP}/installation/register", json=_body(_pem()), timeout=30).json()["company_id"]
    b = requests.post(f"{CP}/installation/register", json=_body(_pem()), timeout=30).json()["company_id"]
    assert a != b
