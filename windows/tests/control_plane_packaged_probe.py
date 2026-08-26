"""End-to-end probe for an installed RoofSpan Office Control Plane.

Used by Windows CI after installing the real MSI. It proves readiness, activation, signed user-bound
pairing, resolution, device listing, and revocation without using customer credentials.
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

BASE = os.environ.get("ROOFSPAN_PROBE_BASE", "http://127.0.0.1:8001").rstrip("/")
CP = f"{BASE}/api/control-plane"
EXPECTED_SHA = os.environ.get("ROOFSPAN_EXPECTED_BUILD_SHA", "").strip().lower()
BOOTSTRAP = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
ADMIN = os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")


def wait_ready(timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{BASE}/api/health/control-plane", timeout=5)
            last = response.text
            if response.status_code == 200 and response.json().get("ready") is True:
                return response.json()
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        time.sleep(3)
    raise AssertionError(f"Control Plane did not become ready: {last}")


def signed_headers(private, installation_id: str, body: bytes = b"") -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = reqsig.sign_request(
        private,
        installation_id=installation_id,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return {
        reqsig.H_INSTALLATION: installation_id,
        reqsig.H_TIMESTAMP: timestamp,
        reqsig.H_NONCE: nonce,
        reqsig.H_SIGNATURE: signature,
    }


def main() -> None:
    ready = wait_ready()
    version = requests.get(f"{BASE}/api/version", timeout=10).json()
    assert version["control_plane"]["ready"] is True, version
    assert version["control_plane"]["current_revision"] == version["control_plane"]["migration_head"], version
    if EXPECTED_SHA:
        assert version["build_sha"] == EXPECTED_SHA, (version, EXPECTED_SHA)
    assert version["build_sha"] != "development", version

    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    activation_response = requests.post(
        f"{CP}/activate",
        json={
            "company_name": "Packaged Release Gate Roofing",
            "requested_seats": 5,
            "installation_public_key": public_pem,
            "software_version": version["version"],
            "bootstrap_credential": BOOTSTRAP,
        },
        timeout=20,
    )
    assert activation_response.status_code == 200, activation_response.text
    activation = activation_response.json()
    installation_id = activation["installation_id"]

    expected_user_id = "00000000-0000-0000-0000-000000000123"
    pairing_body = json.dumps(
        {
            "expected_user_id": expected_user_id,
            "expected_user_label": "Packaged Release Gate User",
        },
        separators=(",", ":"),
    ).encode()
    pairing_response = requests.post(
        f"{CP}/pairing/create",
        data=pairing_body,
        headers=signed_headers(private, installation_id, pairing_body),
        timeout=20,
    )
    assert pairing_response.status_code == 200, pairing_response.text
    pairing = pairing_response.json()
    assert pairing["expected_user_id"] == expected_user_id
    assert len(pairing["numeric_code"]) == 6

    resolve_response = requests.post(
        f"{CP}/pairing/resolve",
        json={"token": pairing["token"], "label": "Packaged Gate Device"},
        timeout=20,
    )
    assert resolve_response.status_code == 200, resolve_response.text
    resolved = resolve_response.json()
    assert resolved["expected_user_id"] == expected_user_id
    assert resolved["device_credential"]

    devices_response = requests.get(
        f"{CP}/pairing/devices",
        headers=signed_headers(private, installation_id),
        timeout=20,
    )
    assert devices_response.status_code == 200, devices_response.text
    devices = devices_response.json()["devices"]
    assert any(device["id"] == resolved["device_id"] for device in devices)

    revoke_response = requests.post(
        f"{CP}/pairing/devices/{resolved['device_id']}/revoke",
        headers={"X-RoofSpan-Admin": ADMIN},
        timeout=20,
    )
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "REVOKED"

    print(json.dumps({
        "ok": True,
        "build_sha": version["build_sha"],
        "storage_mode": ready["storage_mode"],
        "migration_head": ready["migration_head"],
        "installation_id": installation_id,
        "device_id": resolved["device_id"],
        "expected_user_id": expected_user_id,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
