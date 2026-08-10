"""Release publication helper. Prepares the versioned + stable installer filenames, computes SHA-256,
and produces the SIGNED update manifest for https://downloads.roofspan.io/update/windows/latest.json.

Does NOT modify AWS. Upload is optional and gated behind explicit AWS credentials + the approved
CloudFront/S3 release path; building/testing the manifest never requires uploading.
"""
from __future__ import annotations

import datetime
import json

from updater.manifest import Manifest, MANIFEST_VERSION, sha256_hex
from updater.signing import sign_manifest

DOWNLOADS_BASE = "https://downloads.roofspan.io"


def stable_name() -> str:
    return "RoofSpanSetup.exe"


def versioned_name(version: str) -> str:
    return f"RoofSpanSetup-{version}.exe"


def stable_url() -> str:
    return f"{DOWNLOADS_BASE}/latest/{stable_name()}"


def versioned_url(version: str) -> str:
    return f"{DOWNLOADS_BASE}/releases/{versioned_name(version)}"


def build_manifest(*, version: str, installer_bytes: bytes, minimum_supported_version: str,
                   required: bool, signing_private_pem: str, release_notes: str | None = None) -> dict:
    m = Manifest(
        manifest_version=MANIFEST_VERSION, version=version,
        minimum_supported_version=minimum_supported_version,
        installer_url=versioned_url(version), sha256=sha256_hex(installer_bytes),
        required=required, release_date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        release_notes=release_notes,
    )
    m.signature = sign_manifest(m, signing_private_pem)
    out = m.payload()
    out["signature"] = m.signature
    return out


def write_manifest_json(manifest: dict) -> str:
    return json.dumps(manifest, indent=2)


def upload_to_cloudfront_release(*args, **kwargs):  # pragma: no cover - HUMAN REQUIRED
    """Optional S3 publish to the approved release path. Requires explicit AWS creds in the
    environment; intentionally not implemented/auto-run here to avoid touching AWS."""
    raise NotImplementedError(
        "Publishing is HUMAN REQUIRED: upload the built installer + signed manifest to the "
        "existing private S3 release path behind downloads.roofspan.io using authorized AWS creds."
    )
