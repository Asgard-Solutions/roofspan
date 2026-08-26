"""End-to-end probe for the hosted Control Plane pairing contract.

Run against a disposable cp_asgi process and PostgreSQL database. It proves that Office registration is
idempotent, signed status/create/list/revoke are installation-owned, numeric pairing resolves on the
same Control Plane, and user binding survives onto the Mobile device.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig

BASE = os.environ.get("CP_PROBE_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
CP = f"{BASE}/api/control-plane"
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")


def wait_ready(timeout=90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{BASE}/ready", timeout=3)
            if response.status_code == 200:
                return
            last = response.text
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(1)
    raise AssertionError(f"Control Plane did not become ready: {last}")


def signed_request(method, path, installation_id, private_key, body=b""):
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = reqsig.sign_request(
        private_key,
        installation_id=installation_id,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    headers = {
        reqsig.H_INSTALLATION: installation_id,
        reqsig.H_TIMESTAMP: timestamp,
        reqsig.H_NONCE: nonce,
        reqsig.H_SIGNATURE: signature,
    }
    return requests.request(
        method,
        f"{CP}{path}",
        data=body,
        headers=headers,
        timeout=15,
    )


def main():
    wait_ready()

    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    registration = {
        "company_name": "Hosted Pairing Probe",
        "requested_seats": 5,
        "installation_public_key": public_pem,
        "software_version": "0.0.0-probe",
        "bootstrap_credential": BOOTSTRAP,
    }

    first = requests.post(f"{CP}/installation/register", json=registration, timeout=20)
    assert first.status_code == 200, first.text
    first_data = first.json()

    second = requests.post(f"{CP}/installation/register", json=registration, timeout=20)
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["installation_id"] == first_data["installation_id"]
    assert second_data["company_id"] == first_data["company_id"]
    assert second_data["license_id"] == first_data["license_id"]

    installation_id = first_data["installation_id"]
    status = signed_request("POST", "/installation/status", installation_id, private_key)
    assert status.status_code == 200, status.text
    assert status.json()["company_id"] == first_data["company_id"]

    user_id = str(uuid.uuid4())
    pairing_body = json.dumps(
        {"expected_user_id": user_id, "expected_user_label": "Jake Probe"},
        separators=(",", ":"),
    ).encode("utf-8")
    pairing = signed_request(
        "POST", "/pairing/create", installation_id, private_key, pairing_body
    )
    assert pairing.status_code == 200, pairing.text
    pairing_data = pairing.json()
    assert len(pairing_data["numeric_code"]) == 6
    assert pairing_data["expected_user_id"] == user_id
    assert pairing_data["qr_payload"]["token"] == pairing_data["token"]
    assert pairing_data["qr_payload"]["installation_id"] == installation_id
    assert pairing_data["relay_endpoint"].startswith("wss://relay.roofspan.io")

    resolved = requests.post(
        f"{CP}/pairing/resolve",
        json={"numeric_code": pairing_data["numeric_code"], "label": "Probe Phone"},
        timeout=15,
    )
    assert resolved.status_code == 200, resolved.text
    resolved_data = resolved.json()
    assert resolved_data["installation_id"] == installation_id
    assert resolved_data["expected_user_id"] == user_id
    assert resolved_data["device_credential"]

    device_id = resolved_data["device_id"]
    revoked = signed_request(
        "POST",
        f"/pairing/devices/{device_id}/revoke-self",
        installation_id,
        private_key,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "REVOKED"

    devices = signed_request("GET", "/pairing/devices", installation_id, private_key)
    assert devices.status_code == 200, devices.text
    matching = [item for item in devices.json()["devices"] if item["id"] == device_id]
    assert matching and matching[0]["status"] == "REVOKED"
    assert matching[0]["expected_user_id"] == user_id

    print("Hosted Control Plane registration + QR/code pairing + revoke contract: PASS")


if __name__ == "__main__":
    main()
