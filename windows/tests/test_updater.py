"""In-container tests for RoofSpan Windows updater/publish logic (no native Windows needed)."""
import json

import pytest

from updater import manifest as M
from updater import signing as S
from updater.orchestrator import UpdateOrchestrator, evaluate_health
from release import publish


@pytest.fixture(scope="module")
def keys():
    return S.generate_keypair()  # (priv_pem, pub_pem)


def _signed(keys, version="1.1.0", minimum="1.0.0", required=False, installer=b"FAKE-INSTALLER-BYTES"):
    priv, _ = keys
    return M.parse_manifest(publish.build_manifest(
        version=version, installer_bytes=installer, minimum_supported_version=minimum,
        required=required, signing_private_pem=priv, release_notes="notes")), installer


# ---- manifest parsing ----

def test_parse_requires_fields():
    with pytest.raises(M.ManifestError):
        M.parse_manifest({"manifest_version": 1, "version": "1.0.0"})


def test_parse_rejects_non_cloudfront_installer_url():
    with pytest.raises(M.ManifestError):
        M.parse_manifest({"manifest_version": 1, "version": "1.0.0", "minimum_supported_version": "1.0.0",
                          "installer_url": "https://evil.example/RoofSpanSetup.exe", "sha256": "x"})


# ---- version comparison + decision ----

def test_version_compare():
    assert M.compare_versions("1.2.0", "1.10.0") == -1
    assert M.compare_versions("2.0.0", "1.9.9") == 1
    assert M.compare_versions("1.0.0", "1.0.0") == 0


def test_update_decision(keys):
    m, _ = _signed(keys, version="1.1.0", minimum="1.0.0", required=False)
    assert M.decide_update("1.1.0", m) == "current"
    assert M.decide_update("1.0.5", m) == "optional"
    assert M.decide_update("0.9.0", m) == "required"      # below minimum
    mreq, _ = _signed(keys, version="1.2.0", minimum="1.0.0", required=True)
    assert M.decide_update("1.1.0", mreq) == "required"   # flagged required


# ---- hash + signature verification ----

def test_hash_verification():
    data = b"installer"
    assert M.verify_package_hash(M.sha256_hex(data), data)
    assert not M.verify_package_hash(M.sha256_hex(b"other"), data)


def test_signature_valid(keys):
    m, _ = _signed(keys)
    assert S.verify_manifest(m, keys[1]) is True


def test_signature_rejects_wrong_key(keys):
    m, _ = _signed(keys)
    _, other_pub = S.generate_keypair()
    assert S.verify_manifest(m, other_pub) is False


def test_signature_rejects_tampered_manifest(keys):
    m, _ = _signed(keys)
    m.version = "9.9.9"  # tamper after signing
    assert S.verify_manifest(m, keys[1]) is False


def test_signature_rejects_tampered_sha256(keys):
    m, _ = _signed(keys)
    m.sha256 = "deadbeef"
    assert S.verify_manifest(m, keys[1]) is False


def test_update_signing_domain_separate_from_entitlements():
    # Distinct domain tag ensures update signatures can't be confused with entitlement signatures.
    assert S.KEY_DOMAIN == "roofspan-windows-update-v1"


# ---- health-check decision ----

def test_health_all_pass():
    probes = {k: True for k in ("backend_running", "api_responsive", "pg_reachable",
                                "migrations_at_head", "licensing_ok", "relay_can_start", "ui_reachable")}
    assert evaluate_health(probes)["healthy"] is True


def test_health_reports_failures():
    r = evaluate_health({"backend_running": True, "pg_reachable": False})
    assert r["healthy"] is False and "pg_reachable" in r["failed"] and "api_responsive" in r["failed"]


# ---- orchestration: success / rollback ----

def _orch(keys, **overrides):
    calls = {"restored": False, "installed": False}
    defaults = dict(
        public_pem=keys[1],
        download=lambda url: b"FAKE-INSTALLER-BYTES",
        backup=lambda: "backup-1",
        migrate=lambda: True,
        health=lambda: {k: True for k in ("backend_running", "api_responsive", "pg_reachable",
                        "migrations_at_head", "licensing_ok", "relay_can_start", "ui_reachable")},
        restore=lambda t: True,
        install_package=lambda b: True,
    )
    defaults.update(overrides)
    return UpdateOrchestrator(**defaults), calls


def test_orchestrator_happy_path(keys):
    m, _ = _signed(keys, version="1.1.0")
    orch, _ = _orch(keys)
    r = orch.run(m, "1.0.0")
    assert r.state == "completed" and "healthy" in r.steps and r.decision == "optional"


def test_orchestrator_noop_when_current(keys):
    m, _ = _signed(keys, version="1.0.0", minimum="1.0.0")
    orch, _ = _orch(keys)
    assert orch.run(m, "1.0.0").state == "noop"


def test_orchestrator_blocks_bad_signature(keys):
    m, _ = _signed(keys)
    m.signature = "AAAA"  # invalid
    orch, _ = _orch(keys)
    r = orch.run(m, "1.0.0")
    assert r.state == "blocked" and "signature" in r.error


def test_orchestrator_blocks_hash_mismatch(keys):
    m, _ = _signed(keys, installer=b"REAL")
    orch, _ = _orch(keys, download=lambda url: b"TAMPERED")
    r = orch.run(m, "1.0.0")
    assert r.state == "blocked" and "hash" in r.error


def test_orchestrator_rolls_back_on_migration_failure(keys):
    m, _ = _signed(keys, version="1.1.0")
    restored = {"v": False}

    def restore(t):
        restored["v"] = True
        return True

    def migrate():
        raise RuntimeError("alembic boom")

    orch, _ = _orch(keys, migrate=migrate, restore=restore)
    r = orch.run(m, "1.0.0")
    assert r.state == "rolled_back" and restored["v"] and "restored" in r.steps


def test_orchestrator_rolls_back_on_health_failure(keys):
    m, _ = _signed(keys, version="1.1.0")
    orch, _ = _orch(keys, health=lambda: {"backend_running": False})
    r = orch.run(m, "1.0.0")
    assert r.state == "rolled_back" and "health check failed" in r.error


# ---- publish helper ----

def test_filename_and_url_generation():
    assert publish.stable_name() == "RoofSpanSetup.exe"
    assert publish.versioned_name("1.0.0") == "RoofSpanSetup-1.0.0.exe"
    assert publish.stable_url() == "https://downloads.roofspan.io/latest/RoofSpanSetup.exe"
    assert publish.versioned_url("1.2.3") == "https://downloads.roofspan.io/releases/RoofSpanSetup-1.2.3.exe"


def test_build_manifest_roundtrip(keys):
    data = b"the-installer"
    man = publish.build_manifest(version="1.3.0", installer_bytes=data,
                                 minimum_supported_version="1.0.0", required=False,
                                 signing_private_pem=keys[0])
    parsed = M.parse_manifest(json.dumps(man))
    assert parsed.sha256 == M.sha256_hex(data)
    assert S.verify_manifest(parsed, keys[1]) is True
    assert parsed.installer_url == "https://downloads.roofspan.io/releases/RoofSpanSetup-1.3.0.exe"


def test_upload_is_human_required():
    with pytest.raises(NotImplementedError):
        publish.upload_to_cloudfront_release()
