"""RC: Office/Field version compatibility gate + legacy Field status mapping (Office side).

Field 1.1.0 sends X-RoofSpan-App-Version; Field 1.0.x sends nothing. The Office relay tunnel marks every
device request with X-RoofSpan-Relay-Forwarded, so a relayed request without a version is Field 1.0.x.
"""
import asyncio
import json
import os
import uuid

import requests

from relay.tunnel_client import InstallationTunnel

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER = {"email": "pjacobsen@asgardsolution.io", "password": "RoofSpan#Owner2026"}
FIELD_NEW = {"X-RoofSpan-App-Version": "1.1.0"}


def _auth():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=20)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_office_reports_release_version():
    v = requests.get(f"{API}/version", timeout=20).json()
    assert v["version"] == "0.5.0" and v["display_version"] == "0.5.0-dev"


def test_field_version_matrix_on_office_050():
    h = _auth()
    assert requests.get(f"{API}/mobile/leads", headers={**h, **FIELD_NEW}, timeout=20).status_code == 200
    r = requests.get(f"{API}/mobile/leads", headers={**h, "X-RoofSpan-App-Version": "1.0.0"}, timeout=20)
    assert r.status_code == 426
    d = r.json()["detail"]
    assert d["code"] == "must_update" and d["app"] == "field" and d["min_supported"] == "1.1.0"
    assert "Update RoofSpan Field" in d["message"]
    # Office web (not relayed, no version header) keeps using the shared photo/mobile endpoints.
    assert requests.get(f"{API}/mobile/leads", headers=h, timeout=20).status_code == 200


def test_relayed_request_without_version_is_field_10():
    h = _auth()
    relayed = {**h, "X-RoofSpan-Relay-Forwarded": "1"}
    r = requests.get(f"{API}/mobile/leads", headers=relayed, timeout=20)
    assert r.status_code == 426 and r.json()["detail"]["code"] == "must_update"
    w = requests.post(f"{API}/mobile/leads", headers=relayed, json={"name": "RC compat should not exist"}, timeout=20)
    assert w.status_code == 426  # rejected before any write
    # Relay photo-image proxy (read-only, no app headers) is not blocked by the gate.
    p = requests.get(f"{API}/mobile/photos/{uuid.uuid4()}/content", headers=relayed, timeout=20)
    assert p.status_code != 426
    assert requests.get(f"{API}/mobile/leads", headers={**relayed, **FIELD_NEW}, timeout=20).status_code == 200


def test_tunnel_marks_device_requests_and_strips_spoofed_marker():
    token = _auth()["Authorization"]
    sent = []

    class _WS:
        async def send(self, data):
            sent.append(json.loads(data))

    t = InstallationTunnel("ws://unused", "iid", None, "http://localhost:8001")
    frame = {"request_id": "r1", "method": "GET", "path": "/api/mobile/leads", "query": "",
             "headers": {"Authorization": token, "x-roofspan-relay-forwarded": "0"}, "body": ""}
    asyncio.run(t._forward(_WS(), frame))
    assert sent[-1]["status"] == 426
    frame["headers"] = {"Authorization": token, **FIELD_NEW}
    asyncio.run(t._forward(_WS(), frame))
    assert sent[-1]["status"] == 200


def test_legacy_interested_status_from_field_10_queue_maps_to_qualified():
    h = {**_auth(), **FIELD_NEW}
    c = requests.post(f"{API}/mobile/leads", headers=h, json={"name": "RC legacy status", "status": "interested"}, timeout=20)
    assert c.status_code == 201, c.text
    lead = c.json()
    assert lead["status"] == "qualified"
    u = requests.patch(f"{API}/mobile/leads/{lead['id']}", headers=h, json={"status": "contacted"}, timeout=20)
    assert u.status_code == 200, u.text
    u = requests.patch(f"{API}/mobile/leads/{lead['id']}", headers=h, json={"status": "interested"}, timeout=20)
    assert u.status_code == 200 and u.json()["status"] == "qualified"
    bad = requests.patch(f"{API}/mobile/leads/{lead['id']}", headers=h, json={"status": "bogus"}, timeout=20)
    assert bad.status_code == 422
