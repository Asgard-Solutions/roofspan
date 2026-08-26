"""End-to-end probe for hosted Control Plane pairing and Secure Relay.

Run against a disposable cp_asgi process and PostgreSQL database. It proves:
- idempotent Office registration on the hosted Control Plane;
- signed installation status/create/list/revoke ownership;
- numeric pairing resolve and user binding on the same Control Plane;
- installation challenge authentication with the same Ed25519 identity;
- paired-device authentication and request/response routing through the hosted Relay.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import requests
import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import reqsig
from relay import protocol as P

BASE = os.environ.get("CP_PROBE_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
CP = f"{BASE}/api/control-plane"
WS_BASE = BASE.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
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


async def prove_relay_route(installation_id, private_key, resolved_data):
    """Open both hosted WebSockets and prove one Mobile request reaches the installation tunnel."""
    installation_ready = asyncio.Event()
    route_complete = asyncio.Event()
    response_body = b'{"status":"ok","source":"installation-tunnel"}'

    async def installation_side():
        async with websockets.connect(
            f"{WS_BASE}/api/relay/installation",
            max_size=16 * 1024 * 1024,
        ) as ws:
            await ws.send(
                P.dumps(
                    {
                        "type": P.T_HELLO,
                        "installation_id": installation_id,
                        "protocol": P.PROTOCOL_VERSION,
                    }
                )
            )
            challenge = P.loads(await ws.recv())
            assert challenge["type"] == P.T_CHALLENGE, challenge
            nonce = challenge["nonce"]
            timestamp = str(int(time.time()))
            signature = reqsig.sign_request(
                private_key,
                installation_id=installation_id,
                timestamp=timestamp,
                nonce=nonce,
                body=nonce.encode(),
            )
            await ws.send(
                P.dumps(
                    {
                        "type": P.T_AUTH,
                        "timestamp": timestamp,
                        "signature": signature,
                    }
                )
            )
            ready = P.loads(await ws.recv())
            assert ready["type"] == P.T_READY, ready
            installation_ready.set()

            request_frame = P.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert request_frame["type"] == P.T_REQUEST, request_frame
            assert request_frame["path"] == "/api/health"
            await ws.send(
                P.dumps(
                    {
                        "type": P.T_RESPONSE,
                        "request_id": request_frame["request_id"],
                        "status": 200,
                        "headers": {"content-type": "application/json"},
                        "body": P.b64e(response_body),
                    }
                )
            )
            await asyncio.wait_for(route_complete.wait(), timeout=10)
            await ws.send(P.dumps({"type": P.T_BYE}))

    async def mobile_side():
        await asyncio.wait_for(installation_ready.wait(), timeout=10)
        async with websockets.connect(
            f"{WS_BASE}/api/relay/mobile",
            max_size=16 * 1024 * 1024,
        ) as ws:
            await ws.send(
                P.dumps(
                    {
                        "type": P.T_HELLO,
                        "installation_id": installation_id,
                        "device_id": resolved_data["device_id"],
                        "device_credential": resolved_data["device_credential"],
                        "protocol": P.PROTOCOL_VERSION,
                    }
                )
            )
            ready = P.loads(await ws.recv())
            assert ready["type"] == P.T_READY, ready
            request_id = uuid.uuid4().hex
            await ws.send(
                P.dumps(
                    {
                        "type": P.T_REQUEST,
                        "request_id": request_id,
                        "method": "GET",
                        "path": "/api/health",
                        "headers": {},
                        "body": "",
                    }
                )
            )
            response = P.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert response["type"] == P.T_RESPONSE, response
            assert response["request_id"] == request_id
            assert response["status"] == 200
            assert P.b64d(response["body"]) == response_body
            route_complete.set()
            await ws.send(P.dumps({"type": P.T_BYE}))

    await asyncio.wait_for(
        asyncio.gather(installation_side(), mobile_side()),
        timeout=25,
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

    asyncio.run(prove_relay_route(installation_id, private_key, resolved_data))

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

    print("Hosted registration + QR/code pairing + authenticated Relay routing + revoke: PASS")


if __name__ == "__main__":
    main()
