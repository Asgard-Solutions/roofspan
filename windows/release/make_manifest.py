"""CLI: build the signed Windows update manifest (latest.json). No AWS upload.

  python windows/release/make_manifest.py --version 1.0.0 --installer path/to/RoofSpanSetup-1.0.0.exe \
      --min-supported 1.0.0 --signing-key path/to/update_signing_private.pem --out latest.json
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import version as ver  # noqa: E402
from release import publish  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=ver.ROOFSPAN_VERSION, help="defaults to windows/VERSION")
    ap.add_argument("--installer", required=True)
    ap.add_argument("--min-supported", default=ver.ROOFSPAN_VERSION)
    ap.add_argument("--signing-key", required=True, help="Ed25519 UPDATE signing private key PEM (offline)")
    ap.add_argument("--required", action="store_true")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--out", default="latest.json")
    a = ap.parse_args()

    with open(a.installer, "rb") as f:
        installer_bytes = f.read()
    with open(a.signing_key, "r") as f:
        priv = f.read()

    manifest = publish.build_manifest(
        version=a.version, installer_bytes=installer_bytes, minimum_supported_version=a.min_supported,
        required=a.required, signing_private_pem=priv, release_notes=a.notes)
    with open(a.out, "w") as f:
        f.write(publish.write_manifest_json(manifest))
    print(f"wrote {a.out}  sha256={manifest['sha256']}  version={manifest['version']}")


if __name__ == "__main__":
    main()
