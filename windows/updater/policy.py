"""Update trust policy shared by the checker and the broker (each calls it independently).

Every rejection uses a stable reason code; messages never contain secrets or caller-controlled text.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .manifest import ManifestError, compare_versions, parse_manifest
from .signing import verify_manifest

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
THUMB = re.compile(r"^[0-9A-F]{40}$")
REQUEST_KEYS = {"request_version", "operation", "request_id", "manifest", "expected_version", "created_utc"}
REQUEST_MAX_AGE = _dt.timedelta(hours=24)
REQUEST_MAX_BYTES = 256 * 1024
INSTALLER_FIXED_ARGS = ("/quiet", "/norestart", "/log")
SID_SYSTEM, SID_ADMINISTRATORS = "S-1-5-18", "S-1-5-32-544"


class Rejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def service_sid(name: str) -> str:
    """Windows per-service SID (NT SERVICE\\<name>): S-1-5-80-<SHA-1 of the upper-cased UTF-16LE name>."""
    digest = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(x) for x in struct.unpack("<5I", digest))


# The only principals allowed to own or write the broker request (file and its folder).
REQUEST_WRITER_SIDS = frozenset({SID_SYSTEM, SID_ADMINISTRATORS, service_sid("RoofSpanUpdateService")})


def authorize_request_provenance(prov) -> None:
    """Caller authorization: the request must have been written by the update checker (or SYSTEM/Admins)
    and nobody else may be able to write it. Missing facts fail closed."""
    if not isinstance(prov, dict):
        raise Rejected("REQUEST_NOT_AUTHORIZED")
    for part in ("file", "dir"):
        facts = prov.get(part)
        if not isinstance(facts, dict) or not isinstance(facts.get("writers"), (list, tuple)):
            raise Rejected("REQUEST_NOT_AUTHORIZED")
        if facts.get("owner") not in REQUEST_WRITER_SIDS:
            raise Rejected("REQUEST_NOT_AUTHORIZED")
        if set(facts["writers"]) - REQUEST_WRITER_SIDS:
            raise Rejected("REQUEST_ACL_TOO_BROAD")


def assert_fixed_argv(argv, staged_path: str, log_path: str) -> None:
    """The installer command line is constant: <broker staging copy> /quiet /norestart /log <broker log>."""
    if list(argv) != [staged_path, *INSTALLER_FIXED_ARGS, log_path]:
        raise Rejected("INSTALLER_ARGV_NOT_FIXED")


@dataclass
class TrustPolicy:
    public_keys: list            # PEM strings: active first, optional next key (rotation)
    channel: str
    allowed_hosts: tuple = ("downloads.roofspan.io",)
    publisher_subject: str = ""
    publisher_thumbprints: tuple = field(default_factory=tuple)

    @classmethod
    def load(cls, policy_json: str, public_keys: list) -> "TrustPolicy":
        d = json.loads(policy_json)
        thumbs = tuple(str(t).upper() for t in d.get("publisher_thumbprints", []))
        if not d.get("publisher_subject") or not thumbs or not all(THUMB.match(t) for t in thumbs):
            raise Rejected("POLICY_INVALID")
        if not public_keys:
            raise Rejected("POLICY_NO_PUBLIC_KEY")
        return cls(public_keys=list(public_keys), channel=str(d["channel"]),
                   allowed_hosts=tuple(d.get("allowed_hosts") or ("downloads.roofspan.io",)),
                   publisher_subject=str(d["publisher_subject"]), publisher_thumbprints=thumbs)


def _utc(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)


def verify_signed_manifest(raw, policy: TrustPolicy):
    """Signature FIRST: nothing in the manifest is interpreted until a trusted key verifies it."""
    try:
        m = parse_manifest(raw)
    except (ManifestError, ValueError, TypeError, KeyError):
        raise Rejected("MANIFEST_MALFORMED")
    def _ok(key):
        try:
            return verify_manifest(m, key)
        except Exception:  # noqa: BLE001 - an unusable key verifies nothing
            return False
    if not any(_ok(k) for k in policy.public_keys):
        raise Rejected("MANIFEST_SIGNATURE_INVALID")
    return m


def validate_manifest(m, policy: TrustPolicy, installed_version: str, failed_versions: set, now=None) -> str:
    """Return 'required' or 'optional', or raise Rejected. 'current' -> Rejected('NO_UPDATE')."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if not m.channel or not m.expires_at or not m.published_at:
        raise Rejected("MANIFEST_MISSING_FIELD")
    if m.channel != policy.channel:
        raise Rejected("CHANNEL_MISMATCH")
    try:
        if _utc(m.expires_at) <= now:
            raise Rejected("MANIFEST_EXPIRED")
        if _utc(m.published_at) > now + _dt.timedelta(minutes=10):
            raise Rejected("MANIFEST_FROM_FUTURE")
    except ValueError:
        raise Rejected("MANIFEST_MALFORMED")
    if not re.fullmatch(r"[0-9a-f]{64}", m.sha256):
        raise Rejected("MANIFEST_MALFORMED")
    validate_installer_url(m.installer_url, m.version, policy)
    if compare_versions(m.version, installed_version) <= 0:
        raise Rejected("NO_UPDATE" if m.version == installed_version else "DOWNGRADE_REJECTED")
    if compare_versions(installed_version, m.minimum_supported_version) < 0:
        raise Rejected("BELOW_MINIMUM_SUPPORTED")
    if m.version in failed_versions:
        raise Rejected("VERSION_PREVIOUSLY_FAILED")
    return "required" if m.required else "optional"


def validate_installer_url(url: str, version: str, policy: TrustPolicy) -> None:
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname not in policy.allowed_hosts or u.username or u.password or u.port
            or u.query or u.fragment or u.netloc != u.hostname
            or u.path != f"/releases/RoofSpanSetup-{version}.exe"):
        raise Rejected("URL_NOT_ALLOWED")


def validate_request(raw: bytes, policy: TrustPolicy, installed_version: str, failed: set, now=None):
    """Broker side: the request carries no paths/urls/commands; everything is re-derived and re-verified."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if not isinstance(raw, bytes) or len(raw) > REQUEST_MAX_BYTES:
        raise Rejected("REQUEST_MALFORMED")
    try:
        req = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Rejected("REQUEST_MALFORMED")
    if not isinstance(req, dict) or set(req) != REQUEST_KEYS:
        raise Rejected("REQUEST_UNEXPECTED_FIELDS")
    if req["request_version"] != 1 or req["operation"] != "install":
        raise Rejected("REQUEST_OPERATION_NOT_ALLOWED")
    if not isinstance(req["request_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", req["request_id"]):
        raise Rejected("REQUEST_MALFORMED")
    if not isinstance(req["expected_version"], str) or not SEMVER.match(req["expected_version"]):
        raise Rejected("REQUEST_MALFORMED")
    try:
        age = now - _utc(req["created_utc"])
    except (ValueError, TypeError):
        raise Rejected("REQUEST_MALFORMED")
    if age > REQUEST_MAX_AGE or age < -_dt.timedelta(minutes=10):
        raise Rejected("REQUEST_STALE")
    if not isinstance(req["manifest"], dict):
        raise Rejected("REQUEST_MALFORMED")
    m = verify_signed_manifest(req["manifest"], policy)
    if m.version != req["expected_version"]:
        raise Rejected("REQUEST_VERSION_MISMATCH")
    validate_manifest(m, policy, installed_version, failed, now)
    return req, m


def evaluate_signature(info: dict, policy: TrustPolicy) -> None:
    """info from authenticode.inspect(); fail closed on anything not positively established."""
    if not info.get("signed"):
        raise Rejected("AUTHENTICODE_UNSIGNED")
    if info.get("revocation") == "revoked":
        raise Rejected("AUTHENTICODE_REVOKED")
    if info.get("revocation") == "unknown":
        raise Rejected("AUTHENTICODE_REVOCATION_UNKNOWN")
    if not info.get("trusted") or info.get("revocation") != "good":
        raise Rejected("AUTHENTICODE_UNTRUSTED")
    if not info.get("timestamped"):
        raise Rejected("AUTHENTICODE_NO_TIMESTAMP")
    if info.get("subject") != policy.publisher_subject:
        raise Rejected("PUBLISHER_MISMATCH")
    if str(info.get("thumbprint", "")).upper() not in policy.publisher_thumbprints:
        raise Rejected("PUBLISHER_THUMBPRINT_NOT_APPROVED")
