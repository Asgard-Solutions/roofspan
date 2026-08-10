"""Update orchestration + health-check decision logic (pure; Windows-native steps injected).

Flow: validate manifest+signature -> compare/policy -> download -> verify hash+signature -> backup
-> quiesce -> migrate (Alembic) -> health-check -> complete OR rollback/restore. Never marks success
on exit-code-0 alone; a failed migration/health-check triggers restore from the pre-update backup.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from updater.manifest import Manifest, decide_update, verify_package_hash
from updater.signing import verify_manifest

HEALTH_CHECKS = ("backend_running", "api_responsive", "pg_reachable", "migrations_at_head",
                 "licensing_ok", "relay_can_start", "ui_reachable")


def evaluate_health(probes: dict) -> dict:
    failed = [k for k in HEALTH_CHECKS if not probes.get(k)]
    return {"healthy": not failed, "failed": failed}


@dataclass
class UpdateResult:
    state: str                       # noop | completed | rolled_back | failed | blocked
    decision: str = "current"
    steps: list = field(default_factory=list)
    error: str | None = None


class UpdateOrchestrator:
    """Windows-specific effects are injected so the orchestration is fully testable in-container.

    Callables:
      download(url) -> bytes
      backup() -> token
      quiesce() / resume()
      migrate() -> bool          (Alembic upgrade; False/raise on failure)
      health() -> dict           (probe map for evaluate_health)
      restore(token) -> bool
      install_package(bytes) -> bool
    """

    def __init__(self, *, public_pem, download, backup, migrate, health, restore,
                 install_package, quiesce=lambda: None, resume=lambda: None):
        self.public_pem = public_pem
        self.download = download
        self.backup = backup
        self.migrate = migrate
        self.health = health
        self.restore = restore
        self.install_package = install_package
        self.quiesce = quiesce
        self.resume = resume

    def run(self, manifest: Manifest, current_version: str) -> UpdateResult:
        steps: list[str] = []
        # 1) authenticate the manifest before trusting anything in it
        if not verify_manifest(manifest, self.public_pem):
            return UpdateResult(state="blocked", steps=steps, error="manifest signature invalid")
        steps.append("manifest_verified")

        # 2) version policy
        decision = decide_update(current_version, manifest)
        if decision == "current":
            return UpdateResult(state="noop", decision=decision, steps=steps)
        steps.append(f"decision:{decision}")

        # 3) download + verify package (hash — signature already authenticated the sha256)
        pkg = self.download(manifest.installer_url)
        steps.append("downloaded")
        if not verify_package_hash(manifest.sha256, pkg):
            return UpdateResult(state="blocked", decision=decision, steps=steps, error="package hash mismatch")
        steps.append("package_verified")

        # 4) backup BEFORE mutating anything
        token = self.backup()
        steps.append("backup")

        try:
            self.quiesce()
            steps.append("quiesced")
            if not self.install_package(pkg):
                raise RuntimeError("install failed")
            steps.append("installed")
            if not self.migrate():
                raise RuntimeError("migration failed")
            steps.append("migrated")
            self.resume()
            health = evaluate_health(self.health())
            if not health["healthy"]:
                raise RuntimeError("health check failed: " + ",".join(health["failed"]))
            steps.append("healthy")
            return UpdateResult(state="completed", decision=decision, steps=steps)
        except Exception as e:  # noqa: BLE001
            restored = False
            try:
                restored = self.restore(token)
            finally:
                self.resume()
            steps.append("restored" if restored else "restore_failed")
            return UpdateResult(state="rolled_back" if restored else "failed",
                                decision=decision, steps=steps, error=str(e))
