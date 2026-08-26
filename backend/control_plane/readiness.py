"""Process-local Control Plane readiness state.

The embedded Control Plane is optional for ordinary Office workflows, but Mobile Access must fail
closed until its schema, migrations, signing key, and version policy are fully initialized.  This
module keeps the public status intentionally small and safe: no connection strings, credentials,
private keys, SQL text, or traceback fragments are exposed through API responses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any


_DEFAULT_MESSAGE = "RoofSpan Mobile Access is still initializing."
_UNAVAILABLE_MESSAGE = (
    "RoofSpan Mobile Access is not initialized on this Office installation. "
    "See backend-service.log or contact RoofSpan support."
)


class ControlPlaneUnavailable(RuntimeError):
    """Raised by API dependencies when the embedded Control Plane is not ready."""

    def __init__(self, status: dict[str, Any]):
        self.status = status
        super().__init__(status.get("message") or _UNAVAILABLE_MESSAGE)


@dataclass(frozen=True)
class ControlPlaneStatus:
    ready: bool = False
    state: str = "starting"
    code: str = "initializing"
    message: str = _DEFAULT_MESSAGE
    storage_mode: str | None = None
    target_schema: str | None = None
    migration_head: str | None = None
    current_revision: str | None = None
    missing_tables: tuple[str, ...] = field(default_factory=tuple)
    missing_columns: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    repair_action: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_lock = RLock()
_status = ControlPlaneStatus()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot() -> dict[str, Any]:
    with _lock:
        result = asdict(_status)
    result["missing_tables"] = list(result["missing_tables"])
    result["missing_columns"] = list(result["missing_columns"])
    result["warnings"] = list(result["warnings"])
    return result


def mark_starting(*, storage_mode: str | None = None, target_schema: str | None = None,
                  migration_head: str | None = None) -> dict[str, Any]:
    global _status
    with _lock:
        _status = ControlPlaneStatus(
            ready=False,
            state="starting",
            code="initializing",
            message=_DEFAULT_MESSAGE,
            storage_mode=storage_mode,
            target_schema=target_schema,
            migration_head=migration_head,
            updated_at=_now(),
        )
    return snapshot()


def mark_ready(report: dict[str, Any]) -> dict[str, Any]:
    global _status
    with _lock:
        _status = ControlPlaneStatus(
            ready=True,
            state="ready",
            code="ready",
            message="RoofSpan Mobile Access is ready.",
            storage_mode=report.get("storage_mode"),
            target_schema=report.get("target_schema"),
            migration_head=report.get("migration_head"),
            current_revision=report.get("current_revision"),
            missing_tables=tuple(report.get("missing_tables") or ()),
            missing_columns=tuple(report.get("missing_columns") or ()),
            warnings=tuple(report.get("warnings") or ()),
            repair_action=report.get("repair_action"),
            updated_at=_now(),
        )
    return snapshot()


def mark_failed(code: str, message: str | None = None,
                report: dict[str, Any] | None = None) -> dict[str, Any]:
    global _status
    report = report or {}
    with _lock:
        _status = ControlPlaneStatus(
            ready=False,
            state="failed",
            code=code or "initialization_failed",
            message=message or _UNAVAILABLE_MESSAGE,
            storage_mode=report.get("storage_mode"),
            target_schema=report.get("target_schema"),
            migration_head=report.get("migration_head"),
            current_revision=report.get("current_revision"),
            missing_tables=tuple(report.get("missing_tables") or ()),
            missing_columns=tuple(report.get("missing_columns") or ()),
            warnings=tuple(report.get("warnings") or ()),
            repair_action=report.get("repair_action"),
            updated_at=_now(),
        )
    return snapshot()


def require_ready() -> dict[str, Any]:
    status = snapshot()
    if not status["ready"]:
        raise ControlPlaneUnavailable(status)
    return status


def reset_for_tests() -> None:
    """Reset module state. Test-only helper; production code should never call this."""
    global _status
    with _lock:
        _status = ControlPlaneStatus()
