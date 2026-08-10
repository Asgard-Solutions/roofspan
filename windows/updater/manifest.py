"""RoofSpan Windows update manifest + verification (runs on the installed box; pure/testable).

The updater NEVER trusts the URL/version alone: every package is verified by SHA-256 AND an
Ed25519 signature over the canonical manifest (see signing.py). Update-signing is a SEPARATE trust
domain from licensing entitlement signing.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

MANIFEST_VERSION = 1

_REQUIRED_FIELDS = ("manifest_version", "version", "minimum_supported_version", "installer_url", "sha256")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ManifestError(ValueError):
    pass


@dataclass
class Manifest:
    manifest_version: int
    version: str
    minimum_supported_version: str
    installer_url: str
    sha256: str
    required: bool = False
    published_at: str | None = None
    release_notes: str | None = None
    signature: str | None = None

    def payload(self) -> dict:
        """Canonical signed payload = all fields except the signature itself."""
        d = {k: v for k, v in self.__dict__.items() if k != "signature" and v is not None}
        return d


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_manifest(raw: str | bytes | dict) -> Manifest:
    obj = raw if isinstance(raw, dict) else json.loads(raw)
    if not isinstance(obj, dict):
        raise ManifestError("manifest must be a JSON object")
    for f in _REQUIRED_FIELDS:
        if f not in obj or obj[f] in (None, ""):
            raise ManifestError(f"missing manifest field: {f}")
    if int(obj["manifest_version"]) != MANIFEST_VERSION:
        raise ManifestError(f"unsupported manifest_version {obj['manifest_version']}")
    for vf in ("version", "minimum_supported_version"):
        if not _SEMVER_RE.match(str(obj[vf])):
            raise ManifestError(f"invalid semantic version in {vf}: {obj[vf]!r}")
    if not str(obj["installer_url"]).startswith("https://downloads.roofspan.io/"):
        raise ManifestError("installer_url must be served from downloads.roofspan.io (CloudFront)")
    return Manifest(
        manifest_version=int(obj["manifest_version"]), version=str(obj["version"]),
        minimum_supported_version=str(obj["minimum_supported_version"]),
        installer_url=str(obj["installer_url"]), sha256=str(obj["sha256"]).lower(),
        required=bool(obj.get("required", False)),
        published_at=obj.get("published_at") or obj.get("release_date"),
        release_notes=obj.get("release_notes"), signature=obj.get("signature"),
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_package_hash(expected_sha256: str, data: bytes) -> bool:
    return sha256_hex(data).lower() == str(expected_sha256).lower()


# ---- version policy ----

def _parse_ver(v: str):
    return [int(x) for x in (str(v or "0").split(".") + ["0", "0", "0"])[:3] if x.isdigit() or x == "0"] or [0, 0, 0]


def compare_versions(a: str, b: str) -> int:
    A, B = _parse_ver(a), _parse_ver(b)
    for i in range(3):
        if A[i] != B[i]:
            return -1 if A[i] < B[i] else 1
    return 0


def decide_update(current_version: str, m: Manifest) -> str:
    """Return 'required' | 'optional' | 'current'.

    required: installed below the minimum supported, OR a flagged-required newer release.
    optional: a newer non-required release is available.
    current:  installed at/above the manifest version.
    """
    if compare_versions(current_version, m.minimum_supported_version) < 0:
        return "required"
    if compare_versions(current_version, m.version) < 0:
        return "required" if m.required else "optional"
    return "current"
