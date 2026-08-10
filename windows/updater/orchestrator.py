"""Update orchestration + explicit update state machine + health-check logic (pure; Windows-native
steps injected). Never marks success on exit-code-0 alone; a failed install/migration/health-check
triggers restore from the pre-update backup.

State machine (item 18): NOOP / BLOCKED are terminal gates; the apply path progresses
DOWNLOADED -> VERIFIED -> BACKED_UP -> INSTALLING -> MIGRATING -> HEALTH_CHECKING -> COMPLETE, and any
failure after backup transitions to ROLLED_BACK (backup restored) or FAILED (restore also failed).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from updater.manifest import Manifest, decide_update, verify_package_hash
from updater.signing import verify_manifest

HEALTH_CHECKS = ("backend_running", "api_responsive", "pg_reachable", "migrations_at_head",
                 "licensing_ok", "relay_can_start", "ui_reachable")


class UpdateState:
    NOOP = "NOOP"
    BLOCKED = "BLOCKED"
    DOWNLOADED = "DOWNLOADED"
    VERIFIED = "VERIFIED"
    BACKED_UP = "BACKED_UP"
    INSTALLING = "INSTALLING"
    MIGRATING = "MIGRATING"
    HEALTH_CHECKING = "HEALTH_CHECKING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


def evaluate_health(probes: dict) -> dict:
    failed = [k for k in HEALTH_CHECKS if not probes.get(k)]
    return {"healthy": not failed, "failed": failed}


@dataclass
class UpdateResult:
    state: str                       # legacy: noop | completed | rolled_back | failed | blocked
    decision: str = "current"
    steps: list = field(default_factory=list)
    states: list = field(default_factory=list)   # explicit state-machine transitions reached
    final_state: str = ""            # terminal UpdateState (NOOP/BLOCKED/COMPLETE/ROLLED_BACK/FAILED)
    error: str | None = None


class UpdateOrchestrator:
    """Windows-specific effects are injected so the orchestration is fully testable in-container.

    Callables: download(url)->bytes, backup()->token, quiesce()/resume(), migrate()->bool
    (Alembic upgrade), health()->dict (probe map), restore(token)->bool, install_package(bytes)->bool.
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
        states: list[str] = []

        # 1) authenticate the manifest before trusting anything in it
        if not verify_manifest(manifest, self.public_pem):
            return UpdateResult(state="blocked", steps=steps, states=states,
                                final_state=UpdateState.BLOCKED, error="manifest signature invalid")
        steps.append("manifest_verified")

        # 2) version policy
        decision = decide_update(current_version, manifest)
        if decision == "current":
            return UpdateResult(state="noop", decision=decision, steps=steps, states=states,
                                final_state=UpdateState.NOOP)
        steps.append(f"decision:{decision}")

        # 3) download + verify package (SHA-256; signature already authenticated the manifest's sha256)
        pkg = self.download(manifest.installer_url)
        steps.append("downloaded")
        states.append(UpdateState.DOWNLOADED)
        if not verify_package_hash(manifest.sha256, pkg):
            return UpdateResult(state="blocked", decision=decision, steps=steps, states=states,
                                final_state=UpdateState.BLOCKED, error="package hash mismatch")
        steps.append("package_verified")
        states.append(UpdateState.VERIFIED)

        # 4) backup BEFORE mutating anything
        token = self.backup()
        steps.append("backup")
        states.append(UpdateState.BACKED_UP)

        try:
            self.quiesce()
            steps.append("quiesced")
            states.append(UpdateState.INSTALLING)
            if not self.install_package(pkg):
                raise RuntimeError("install failed")
            steps.append("installed")
            states.append(UpdateState.MIGRATING)
            if not self.migrate():
                raise RuntimeError("migration failed")
            steps.append("migrated")
            self.resume()
            states.append(UpdateState.HEALTH_CHECKING)
            health = evaluate_health(self.health())
            if not health["healthy"]:
                raise RuntimeError("health check failed: " + ",".join(health["failed"]))
            steps.append("healthy")
            states.append(UpdateState.COMPLETE)
            return UpdateResult(state="completed", decision=decision, steps=steps, states=states,
                                final_state=UpdateState.COMPLETE)
        except Exception as e:  # noqa: BLE001
            restored = False
            try:
                restored = self.restore(token)
            finally:
                self.resume()
            steps.append("restored" if restored else "restore_failed")
            final = UpdateState.ROLLED_BACK if restored else UpdateState.FAILED
            states.append(final)
            return UpdateResult(state="rolled_back" if restored else "failed", decision=decision,
                                steps=steps, states=states, final_state=final, error=str(e))
