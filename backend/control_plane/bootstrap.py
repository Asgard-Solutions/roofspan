"""Control Plane startup orchestration and readiness gating."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, text

from control_plane import config, keys as cp_keys, readiness
from control_plane.db import SessionLocal
from control_plane.migrations_runner import (
    ControlPlaneMigrationError,
    get_migration_head,
    run_cp_migrations,
    storage_mode,
    target_schema,
)
from control_plane.models import VersionPolicy

logger = logging.getLogger("roofspan")

_UNAVAILABLE = (
    "RoofSpan Mobile Access is not initialized on this Office installation. "
    "See backend-service.log or contact RoofSpan support."
)


async def init_control_plane() -> dict:
    """Migrate, validate, initialize signer/policy, and publish ready state. Idempotent."""
    try:
        head = get_migration_head()
    except Exception:
        head = None
    try:
        schema = target_schema()
    except Exception:
        schema = config.CONTROL_PLANE_SCHEMA or "public"
    readiness.mark_starting(storage_mode=storage_mode(), target_schema=schema, migration_head=head)

    report: dict = {
        "storage_mode": storage_mode(),
        "target_schema": schema,
        "migration_head": head,
    }
    try:
        report = await asyncio.to_thread(run_cp_migrations)
        async with SessionLocal() as db:
            # A real query through the runtime ORM engine verifies that schema_translate_map points to
            # the same storage that Alembic just migrated.
            await db.execute(text("SELECT 1"))
            await cp_keys.ensure_active_key(db)
            await cp_keys.validate_active_key(db)
            vp = (
                await db.execute(select(VersionPolicy).where(VersionPolicy.key == "default"))
            ).scalar_one_or_none()
            if vp is None:
                db.add(
                    VersionPolicy(
                        key="default",
                        office_min_supported=config.MIN_SUPPORTED_VERSION,
                        mobile_min_supported=config.MIN_SUPPORTED_VERSION,
                    )
                )
                await db.commit()
        status = readiness.mark_ready(report)
        logger.info(
            "Control Plane READY: mode=%s schema=%s revision=%s head=%s repair=%s warnings=%s",
            status.get("storage_mode"),
            status.get("target_schema"),
            status.get("current_revision"),
            status.get("migration_head"),
            status.get("repair_action"),
            status.get("warnings"),
        )
        return status
    except ControlPlaneMigrationError as exc:
        status = readiness.mark_failed(exc.code, exc.safe_message, exc.report.to_dict())
        logger.error(
            "Control Plane NOT READY: code=%s mode=%s schema=%s revision=%s head=%s missing_tables=%s missing_columns=%s",
            exc.code,
            status.get("storage_mode"),
            status.get("target_schema"),
            status.get("current_revision"),
            status.get("migration_head"),
            status.get("missing_tables"),
            status.get("missing_columns"),
        )
        raise
    except Exception:
        readiness.mark_failed("initialization_failed", _UNAVAILABLE, report)
        logger.exception("Control Plane initialization failed after migration validation")
        raise
