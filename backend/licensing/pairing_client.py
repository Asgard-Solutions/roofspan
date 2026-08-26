"""Office-side Mobile pairing client.

RoofSpan Office and RoofSpan Mobile must use the same hosted Control Plane. Packaged Office builds use
``CONTROL_PLANE_BASE_URL`` (https://cp.roofspan.io); localhost is supported only through an explicit
development override. Existing Office rows created by the old localhost implementation are verified
against the configured host and transparently re-registered there when the id is unknown.

All installation-owned operations use the installation Ed25519 key. No Control Plane operator/admin
secret is shipped in Office. Error details surfaced to Office are safe and omit SQL, credentials,
connection strings, private keys, and tracebacks.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
import uuid
from urllib.parse import urlparse, urlunparse

import httpx
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppConfig
from licensing import config as lic_config
from licensing import identity, reqsig

log = logging.getLogger("roofspan.pairing")

_DEFAULT_CONTROL_PLANE_ORIGIN = "https://cp.roofspan.io"
_CP_API_PATH = "/api/control-plane"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ControlPlaneError(RuntimeError):
    """Carries a safe, human-readable Control Plane failure reason."""


_SECRET_HINT = (
    "password",
    "secret",
    "postgresql://",
    "postgres://",
    "@",
    "jwt",
    "token=",
    "key=",
    "-----begin",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "traceback",
)


def _normalize_cp_base(raw: str | None) -> str:
    """Normalize a Control Plane origin/full API URL to ``.../api/control-plane``.

    Non-local plain HTTP is rejected so a configuration mistake cannot send installation signatures
    or pairing tokens over an unencrypted connection.
    """
    value = str(raw or "").strip().rstrip("/")
    if not value:
        raise ControlPlaneError("RoofSpan Control Plane URL is not configured.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ControlPlaneError("RoofSpan Control Plane URL is invalid.")
    if parsed.query or parsed.fragment:
        raise ControlPlaneError("RoofSpan Control Plane URL must not contain a query or fragment.")
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in _LOCAL_HOSTS:
        raise ControlPlaneError("RoofSpan Control Plane requires HTTPS.")

    path = parsed.path.rstrip("/")
    if path in {"", "/"}:
        path = _CP_API_PATH
    elif path == "/api":
        path = _CP_API_PATH
    elif not path.endswith(_CP_API_PATH):
        raise ControlPlaneError(
            "RoofSpan Control Plane URL must be an origin or end with /api/control-plane."
        )
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def control_plane_base() -> str:
    """Return the one authoritative Control Plane endpoint used by Office pairing.

    ``CONTROL_PLANE_BASE_URL`` is the canonical packaged setting. Older variable names remain as
    explicit compatibility overrides, but there is no implicit localhost fallback.
    """
    raw = (
        os.environ.get("PAIRING_CONTROL_PLANE_URL")
        or os.environ.get("CONTROL_PLANE_BASE_URL")
        or os.environ.get("LICENSING_CONTROL_PLANE_URL")
        or os.environ.get("INTERNAL_CONTROL_PLANE_URL")
        or _DEFAULT_CONTROL_PLANE_ORIGIN
    )
    return _normalize_cp_base(raw)


def _safe_detail(response: httpx.Response) -> str:
    detail = None
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code")
        elif isinstance(detail, list):
            detail = "Request validation failed."
    except Exception:
        detail = None
    if not detail:
        detail = f"HTTP {response.status_code}"
    detail = str(detail)
    if any(hint in detail.lower() for hint in _SECRET_HINT):
        return f"Control Plane returned HTTP {response.status_code} (details withheld for security)."
    return detail[:300]


def _raise_for_cp(response: httpx.Response, action: str) -> None:
    if response.status_code >= 400:
        raise ControlPlaneError(f"{action} failed: {_safe_detail(response)}")


def _qr_png_data_url(payload: dict) -> str:
    """Render the safe, single-use QR payload locally for the Office UI."""
    if not isinstance(payload, dict) or not payload.get("installation_id") or not payload.get("token"):
        raise ControlPlaneError("Control Plane returned an invalid QR payload.")
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=7,
        border=4,
    )
    qr.add_data(encoded)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


async def _get_installation_row(db: AsyncSession):
    return (
        await db.execute(select(AppConfig).where(AppConfig.key == "installation"))
    ).scalar_one_or_none()


async def _save_installation_value(
    db: AsyncSession,
    row,
    value: dict,
) -> None:
    if row is None:
        db.add(AppConfig(key="installation", value=value))
    else:
        # Assign a new dict so SQLAlchemy JSON change tracking always persists the update.
        row.value = dict(value)
    await db.commit()


async def _send(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            return await client.request(
                method,
                url,
                content=body,
                json=json_body,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ControlPlaneError(
            "RoofSpan could not reach the hosted Control Plane. Check internet access and try again."
        ) from exc


async def _request_signed(
    method: str,
    base: str,
    path: str,
    installation_id: str,
    private_key,
    body: bytes = b"",
) -> httpx.Response:
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
    return await _send(method, f"{base}{path}", body=body, headers=headers)


async def _register_installation(base: str, public_key_pem: str) -> dict:
    response = await _send(
        "POST",
        f"{base}/installation/register",
        json_body={
            "company_name": lic_config.ACTIVATION_COMPANY_NAME,
            "requested_seats": lic_config.ACTIVATION_REQUESTED_SEATS,
            "installation_public_key": public_key_pem,
            "software_version": lic_config.SOFTWARE_VERSION,
            "bootstrap_credential": lic_config.ACTIVATION_BOOTSTRAP_CREDENTIAL,
        },
    )
    _raise_for_cp(response, "Device activation")
    data = response.json()
    for required in ("installation_id", "company_id"):
        if not data.get(required):
            raise ControlPlaneError("Control Plane returned an incomplete activation response.")
    return data


async def ensure_registered(db: AsyncSession) -> tuple[str, object, str]:
    """Verify/migrate this Office registration on the configured hosted Control Plane."""
    base = control_plane_base()
    private_key, public_key_pem = identity.get_or_create_identity()
    row = await _get_installation_row(db)
    value = dict(row.value) if (row and isinstance(row.value, dict)) else {}
    current_id = value.get("cp_installation_id")

    if current_id:
        status = await _request_signed(
            "POST", base, "/installation/status", current_id, private_key
        )
        if 200 <= status.status_code < 300:
            data = status.json()
            changed = False
            if value.get("cp_base_url") != base:
                value["cp_base_url"] = base
                changed = True
            if data.get("company_id") and value.get("cp_company_id") != data["company_id"]:
                value["cp_company_id"] = data["company_id"]
                changed = True
            if changed:
                await _save_installation_value(db, row, value)
            return current_id, private_key, base
        if status.status_code != 404:
            _raise_for_cp(status, "Verify Office registration")

        # A 404 is the expected one-time migration path for ids issued by the obsolete localhost CP.
        log.info(
            "Stored Control Plane installation is unknown on %s; registering the existing public identity",
            urlparse(base).netloc,
        )

    registration = await _register_installation(base, public_key_pem)
    new_id = registration["installation_id"]
    if current_id and current_id != new_id:
        value["cp_previous_installation_id"] = current_id
    value["cp_installation_id"] = new_id
    value["cp_company_id"] = registration["company_id"]
    value["cp_base_url"] = base
    value["cp_registered_at"] = int(time.time())
    await _save_installation_value(db, row, value)
    return new_id, private_key, base


async def create_pairing(
    db: AsyncSession,
    expected_user_id: str | None = None,
    expected_user_label: str | None = None,
) -> dict:
    installation_id, private_key, base = await ensure_registered(db)
    body = b""
    if expected_user_id or expected_user_label:
        body = json.dumps(
            {
                "expected_user_id": expected_user_id,
                "expected_user_label": expected_user_label,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    response = await _request_signed(
        "POST", base, "/pairing/create", installation_id, private_key, body=body
    )
    _raise_for_cp(response, "Create pairing")
    data = response.json()
    data["qr_code_data_url"] = _qr_png_data_url(data.get("qr_payload"))
    data["control_plane_origin"] = urlparse(base).netloc
    return data


async def list_devices(db: AsyncSession) -> dict:
    installation_id, private_key, base = await ensure_registered(db)
    response = await _request_signed(
        "GET", base, "/pairing/devices", installation_id, private_key
    )
    _raise_for_cp(response, "List devices")
    return response.json()


async def revoke_device(db: AsyncSession, device_id: str) -> dict:
    installation_id, private_key, base = await ensure_registered(db)
    response = await _request_signed(
        "POST",
        base,
        f"/pairing/devices/{device_id}/revoke-self",
        installation_id,
        private_key,
    )
    _raise_for_cp(response, "Revoke device")
    return response.json()
