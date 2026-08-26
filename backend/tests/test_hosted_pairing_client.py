"""Regression tests for the Office -> hosted Control Plane pairing contract."""
import asyncio
import base64
from types import SimpleNamespace

import pytest

from licensing import pairing_client


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeDb:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def _clear_cp_env(monkeypatch):
    for key in (
        "PAIRING_CONTROL_PLANE_URL",
        "CONTROL_PLANE_BASE_URL",
        "LICENSING_CONTROL_PLANE_URL",
        "INTERNAL_CONTROL_PLANE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_control_plane_url_uses_canonical_hosted_setting(monkeypatch):
    _clear_cp_env(monkeypatch)
    monkeypatch.setenv("CONTROL_PLANE_BASE_URL", "https://cp.roofspan.io/")
    monkeypatch.setenv("INTERNAL_CONTROL_PLANE_URL", "http://localhost:8001/api/control-plane")
    assert pairing_client.control_plane_base() == "https://cp.roofspan.io/api/control-plane"


def test_control_plane_url_accepts_explicit_local_development_override(monkeypatch):
    _clear_cp_env(monkeypatch)
    monkeypatch.setenv("PAIRING_CONTROL_PLANE_URL", "http://127.0.0.1:8001")
    assert pairing_client.control_plane_base() == "http://127.0.0.1:8001/api/control-plane"


def test_control_plane_url_rejects_non_local_plain_http():
    with pytest.raises(pairing_client.ControlPlaneError, match="requires HTTPS"):
        pairing_client._normalize_cp_base("http://cp.roofspan.io")


def test_qr_data_url_is_a_real_png():
    data_url = pairing_client._qr_png_data_url(
        {
            "v": "1",
            "installation_id": "11111111-1111-1111-1111-111111111111",
            "token": "abcdef0123456789abcdef0123456789",
            "relay": "wss://relay.roofspan.io",
            "expires_at": 1999999999,
        }
    )
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    assert base64.b64decode(data_url[len(prefix):]).startswith(b"\x89PNG\r\n\x1a\n")


def test_legacy_local_registration_is_replaced_by_hosted_registration(monkeypatch):
    old_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    new_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    row = SimpleNamespace(value={"cp_installation_id": old_id, "cp_company_id": "old-company"})
    db = FakeDb()
    private_key = object()

    async def fake_get_row(_db):
        return row

    async def fake_status(method, base, path, installation_id, key, body=b""):
        assert method == "POST"
        assert base == "https://cp.roofspan.io/api/control-plane"
        assert path == "/installation/status"
        assert installation_id == old_id
        assert key is private_key
        return FakeResponse(404, {"detail": "Unknown installation"})

    async def fake_register(base, public_key):
        assert base == "https://cp.roofspan.io/api/control-plane"
        assert public_key == "PUBLIC PEM"
        return {"installation_id": new_id, "company_id": "hosted-company"}

    monkeypatch.setattr(pairing_client, "control_plane_base", lambda: "https://cp.roofspan.io/api/control-plane")
    monkeypatch.setattr(pairing_client.identity, "get_or_create_identity", lambda: (private_key, "PUBLIC PEM"))
    monkeypatch.setattr(pairing_client, "_get_installation_row", fake_get_row)
    monkeypatch.setattr(pairing_client, "_request_signed", fake_status)
    monkeypatch.setattr(pairing_client, "_register_installation", fake_register)

    installation_id, returned_key, base = asyncio.run(pairing_client.ensure_registered(db))

    assert installation_id == new_id
    assert returned_key is private_key
    assert base == "https://cp.roofspan.io/api/control-plane"
    assert row.value["cp_previous_installation_id"] == old_id
    assert row.value["cp_installation_id"] == new_id
    assert row.value["cp_company_id"] == "hosted-company"
    assert row.value["cp_base_url"] == base
    assert db.commits == 1


def test_existing_hosted_registration_is_verified_and_tagged(monkeypatch):
    installation_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    row = SimpleNamespace(value={"cp_installation_id": installation_id})
    db = FakeDb()
    private_key = object()

    async def fake_get_row(_db):
        return row

    async def fake_status(method, base, path, iid, key, body=b""):
        return FakeResponse(200, {"installation_id": iid, "company_id": "hosted-company", "status": "ACTIVE"})

    async def should_not_register(*_args, **_kwargs):
        raise AssertionError("valid hosted registration must not be duplicated")

    monkeypatch.setattr(pairing_client, "control_plane_base", lambda: "https://cp.roofspan.io/api/control-plane")
    monkeypatch.setattr(pairing_client.identity, "get_or_create_identity", lambda: (private_key, "PUBLIC PEM"))
    monkeypatch.setattr(pairing_client, "_get_installation_row", fake_get_row)
    monkeypatch.setattr(pairing_client, "_request_signed", fake_status)
    monkeypatch.setattr(pairing_client, "_register_installation", should_not_register)

    result = asyncio.run(pairing_client.ensure_registered(db))
    assert result[0] == installation_id
    assert row.value["cp_base_url"] == "https://cp.roofspan.io/api/control-plane"
    assert row.value["cp_company_id"] == "hosted-company"
    assert db.commits == 1


def test_create_pairing_attaches_qr_image(monkeypatch):
    private_key = object()
    payload = {
        "v": "1",
        "installation_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "token": "0123456789abcdef0123456789abcdef",
        "relay": "wss://relay.roofspan.io",
        "expires_at": 1999999999,
    }

    async def fake_ensure(_db):
        return payload["installation_id"], private_key, "https://cp.roofspan.io/api/control-plane"

    async def fake_request(method, base, path, installation_id, key, body=b""):
        assert path == "/pairing/create"
        return FakeResponse(
            200,
            {
                "token": payload["token"],
                "numeric_code": "123456",
                "expires_at": "2033-05-18T03:33:19+00:00",
                "qr_payload": payload,
            },
        )

    monkeypatch.setattr(pairing_client, "ensure_registered", fake_ensure)
    monkeypatch.setattr(pairing_client, "_request_signed", fake_request)

    result = asyncio.run(
        pairing_client.create_pairing(
            FakeDb(), expected_user_id="user-1", expected_user_label="Jake Field"
        )
    )
    assert result["numeric_code"] == "123456"
    assert result["qr_code_data_url"].startswith("data:image/png;base64,")
    assert result["control_plane_origin"] == "cp.roofspan.io"
