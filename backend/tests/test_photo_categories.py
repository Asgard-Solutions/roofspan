"""Photo category preset tests: 'Overview' accepted, invalid category 422, lead listing."""
import io
import os
import uuid
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"

# 1x1 PNG
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\x5c\xcd\xff\x69\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_lead(headers):
    r = requests.post(f"{API}/properties", json={
        "address_line1": f"{uuid.uuid4().hex[:6]} Cat St",
        "city": "Austin", "state": "TX", "zip_code": "78701",
        "latitude": 30.2, "longitude": -97.7
    }, headers=headers, timeout=15)
    pid = r.json()["id"]
    r = requests.post(f"{API}/properties/{pid}/convert-to-lead", json={"name": "TEST Cat Lead"}, headers=headers, timeout=15)
    assert r.status_code == 201, r.text
    return r.json(), pid


def test_photo_overview_category_and_invalid_and_list():
    owner = _login(OWNER_EMAIL, OWNER_PASSWORD)
    lead, _ = _make_lead(owner)

    # Overview category succeeds
    files = {"file": ("t.png", io.BytesIO(PNG_BYTES), "image/png")}
    data = {"record_type": "lead", "record_id": lead["id"], "category": "Overview", "description": "TEST"}
    r = requests.post(f"{API}/mobile/photos", files=files, data=data, headers=owner, timeout=30)
    assert r.status_code == 201, r.text
    photo = r.json()
    assert photo.get("category") == "Overview"
    pid = photo["id"]

    # Invalid category -> 422
    files2 = {"file": ("t.png", io.BytesIO(PNG_BYTES), "image/png")}
    data2 = {"record_type": "lead", "record_id": lead["id"], "category": "NotAValidCat"}
    r2 = requests.post(f"{API}/mobile/photos", files=files2, data=data2, headers=owner, timeout=30)
    assert r2.status_code == 422, r2.text

    # List by lead
    lr = requests.get(f"{API}/mobile/photos", params={"record_type": "lead", "record_id": lead["id"]}, headers=owner, timeout=15)
    assert lr.status_code == 200
    assert any(p["id"] == pid for p in lr.json())

    # Content bytes returned
    cr = requests.get(f"{BASE_URL}{photo['content_url']}", headers=owner, timeout=15)
    assert cr.status_code == 200
    assert cr.headers.get("content-type", "").startswith("image/")
    assert len(cr.content) > 0
