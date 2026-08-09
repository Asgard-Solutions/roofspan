"""Phase C0 integration tests: server-side, race-safe active-seat enforcement.

Sets the licensed seat count to the current active-user count + 1, proves one activation succeeds and
the next is rejected (422 with the seat message), on both create and reactivation. Cleans up created
users and restores ACTIVE/50 seats.
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


def _login():
    r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _set_state(headers, state, seats):
    r = requests.post(f"{API}/dev/licensing/set-state", json={"state": state, "seats_licensed": seats}, headers=headers, timeout=15)
    assert r.status_code == 200, r.text


def _active_users(headers):
    return requests.get(f"{API}/subscription", headers=headers, timeout=15).json()["active_users"]


def _create(headers, role="sales"):
    email = f"seat_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/users", json={"email": email, "full_name": "Seat", "password": "SeatTest#2026", "role": role}, headers=headers, timeout=15)
    return r


@pytest.fixture(autouse=True)
def restore():
    owner = _login()
    yield
    _set_state(owner, "ACTIVE", 50)


def test_seat_limit_blocks_creation_over_limit():
    owner = _login()
    created = []
    try:
        active = _active_users(owner)
        _set_state(owner, "ACTIVE", active + 1)  # exactly one free seat
        r1 = _create(owner)
        assert r1.status_code == 201, r1.text
        created.append(r1.json()["id"])
        # now at the limit -> next active user rejected
        r2 = _create(owner)
        assert r2.status_code == 422, r2.text
        assert "licensed" in r2.json()["detail"].lower()
    finally:
        for uid in created:
            requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner, timeout=15)
        _set_state(owner, "ACTIVE", 50)


def test_reactivation_respects_seat_limit():
    owner = _login()
    created = []
    try:
        # create a user (with a free seat) then disable it
        _set_state(owner, "ACTIVE", 50)
        r = _create(owner)
        assert r.status_code == 201, r.text
        uid = r.json()["id"]
        created.append(uid)
        requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner, timeout=15)
        # now fill seats to exactly the active count -> reactivation must be blocked
        active = _active_users(owner)
        _set_state(owner, "ACTIVE", active)  # zero free seats
        rr = requests.patch(f"{API}/users/{uid}", json={"is_active": True}, headers=owner, timeout=15)
        assert rr.status_code == 422, rr.text
        # add a seat -> reactivation now succeeds
        _set_state(owner, "ACTIVE", active + 1)
        rr2 = requests.patch(f"{API}/users/{uid}", json={"is_active": True}, headers=owner, timeout=15)
        assert rr2.status_code == 200, rr2.text
    finally:
        for uid in created:
            requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner, timeout=15)
        _set_state(owner, "ACTIVE", 50)


def test_disabled_users_do_not_consume_seats():
    owner = _login()
    created = []
    try:
        _set_state(owner, "ACTIVE", 50)
        before = _active_users(owner)
        r = _create(owner)
        uid = r.json()["id"]
        created.append(uid)
        assert _active_users(owner) == before + 1
        requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner, timeout=15)
        assert _active_users(owner) == before  # disabled user no longer counts
    finally:
        for uid in created:
            requests.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=owner, timeout=15)
        _set_state(owner, "ACTIVE", 50)
