import os
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import select

from db import engine, SessionLocal
from models import User
from core import hash_password, verify_password
from migrations_runner import run_migrations
from routers import auth, users, audit, integrations, settings, territories, properties, imports, leads
from routers import customers, inspections, estimates, quotes, invoices, jobs
from routers import operations, purchasing, cron, admin_ops, mobile, location_resolution, building_tiles, licensing as licensing_router
from routers import abc_supply
from routers import abc_webhooks
from routers import relay_connector as relay_connector_router
from licensing import config as licensing_config, service as licensing_service
from licensing.middleware import SubscriptionGuardMiddleware
from control_plane.router import router as control_plane_router
from control_plane.installation_router import router as control_plane_installation_router
from control_plane.bootstrap import init_control_plane
from control_plane import readiness as cp_readiness
from version import ROOFSPAN_VERSION, DISPLAY_VERSION, CHANNEL, BUILD_SHA

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("roofspan")

app = FastAPI(title="RoofSpan Office API", version="1.0.0")


@app.get("/api/health")
async def health():
    cp = cp_readiness.snapshot()
    return {
        "status": "ok",
        "service": "roofspan-office",
        "database": "postgresql",
        "version": DISPLAY_VERSION,
        "control_plane": {"ready": cp["ready"], "state": cp["state"], "code": cp["code"]},
    }


@app.get("/api/health/control-plane")
async def control_plane_health():
    """Safe Mobile Access readiness diagnostics; contains no credentials or connection strings."""
    from fastapi.responses import JSONResponse

    status = cp_readiness.snapshot()
    return JSONResponse(status_code=200 if status["ready"] else 503, content=status)


@app.get("/api/version")
async def version():
    """RoofSpan Office software/build and Control Plane migration identity for support diagnostics."""
    cp = cp_readiness.snapshot()
    return {
        "version": ROOFSPAN_VERSION,
        "display_version": DISPLAY_VERSION,
        "channel": CHANNEL,
        "build_sha": BUILD_SHA,
        "service": "roofspan-office",
        "control_plane": {
            "ready": cp["ready"],
            "storage_mode": cp["storage_mode"],
            "migration_head": cp["migration_head"],
            "current_revision": cp["current_revision"],
        },
    }


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(abc_supply.router)
app.include_router(abc_webhooks.public_router)
app.include_router(abc_webhooks.admin_router)
app.include_router(integrations.router)
app.include_router(settings.router)
app.include_router(territories.router)
app.include_router(properties.router)
app.include_router(imports.router)
app.include_router(location_resolution.router)
app.include_router(building_tiles.router)
app.include_router(leads.router)
app.include_router(customers.router)
app.include_router(inspections.router)
from routers import measurements as measurements_router
app.include_router(measurements_router.router)
app.include_router(estimates.router)
from routers import estimating as estimating_router
app.include_router(estimating_router.router)
app.include_router(quotes.router)
from routers import inventory_ops as inventory_ops_router
app.include_router(inventory_ops_router.router)
app.include_router(invoices.router)
app.include_router(jobs.router)
from routers import reporting as reporting_router
app.include_router(reporting_router.router)
app.include_router(reporting_router.dashboard_router)
app.include_router(reporting_router.inv_report_router)
app.include_router(operations.router)
app.include_router(purchasing.router)
app.include_router(cron.router)
app.include_router(admin_ops.router)
from routers import canvass as canvass_router
app.include_router(canvass_router.router)
app.include_router(mobile.router)
app.include_router(licensing_router.router)
app.include_router(relay_connector_router.router)
if licensing_config.LICENSING_MODE == "dev":
    from routers import licensing_dev
    app.include_router(licensing_dev.router)
app.include_router(control_plane_router)
app.include_router(control_plane_installation_router)
from relay.server import router as relay_router  # noqa: E402
from relay.photo_proxy import router as relay_photo_router  # noqa: E402
app.include_router(relay_router)
app.include_router(relay_photo_router)

# Local mock ABC Supply server for development/testing (mounted only when ABC_MOCK_ENABLED is set).
from integrations.abc_supply.config import mock_enabled as _abc_mock_enabled  # noqa: E402
if _abc_mock_enabled():
    from integrations.abc_supply.mock_server import router as abc_mock_router
    app.include_router(abc_mock_router, prefix="/api/abc-mock", tags=["abc-mock"])

# Guard business workflows when the subscription is not ACTIVE/GRACE. Added before CORS so CORS
# remains the outermost middleware (guard 403 responses still receive CORS headers).
app.add_middleware(SubscriptionGuardMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def seed_owner():
    email = os.environ.get("ADMIN_EMAIL", "").lower().strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    name = os.environ.get("ADMIN_NAME", "Owner")
    if not email or not password:
        logger.warning("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping owner seed")
        return
    async with SessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is None:
            db.add(User(email=email, full_name=name, password_hash=hash_password(password), role="owner", is_active=True))
            await db.commit()
            logger.info("Seeded owner account: %s", email)
        elif not verify_password(password, existing.password_hash):
            existing.password_hash = hash_password(password)
            await db.commit()
            logger.info("Updated owner password: %s", email)


async def cleanup_duplicates_then_refresh_locations():
    """Remove conservative RentCast duplicates before spending Mapbox calls on the backfill."""
    from property_dedup import cleanup_duplicate_properties
    from location_upgrade import refresh_existing_property_locations

    try:
        stats = await cleanup_duplicate_properties()
        logger.info("Duplicate property cleanup complete: scanned=%d merged=%d", stats["scanned"], stats["merged"])
    except Exception:
        logger.exception("Duplicate property cleanup failed; continuing with location backfill")
    await refresh_existing_property_locations()


@app.on_event("startup")
async def on_startup():
    # Migration-driven business schema. The Windows SCM host pre-applies migrations so failures
    # propagate directly before uvicorn starts; normal/dev execution still runs them here.
    if os.environ.get("ROOFSPAN_MIGRATIONS_PREAPPLIED") != "1":
        await asyncio.to_thread(run_migrations)
    await seed_owner()
    async with SessionLocal() as db:
        await licensing_service.bootstrap(db)
    try:
        await init_control_plane()
    except Exception:
        # Office remains usable, but every Control Plane/Mobile pairing route fails closed with a safe
        # 503 until a later restart completes migration and readiness validation.
        logger.exception(
            "Control Plane init failed (non-fatal for Office; Mobile Access remains unavailable)"
        )
    from relay.hub import hub as relay_hub
    await relay_hub.startup()

    # Existing RentCast properties are de-duplicated first, then upgraded in place. Both operations
    # are background/idempotent so users do not need to delete or re-import territories.
    asyncio.create_task(cleanup_duplicates_then_refresh_locations())

    # In-process scheduled auto-backup (user-configurable time; file-based, survives restores).
    from services import backup as _backup_svc
    asyncio.create_task(_backup_svc.scheduler_loop())

    logger.info("RoofSpan Office backend ready (build_sha=%s, cp_ready=%s)", BUILD_SHA, cp_readiness.snapshot()["ready"])


@app.on_event("shutdown")
async def on_shutdown():
    from relay.hub import hub as relay_hub
    await relay_hub.shutdown()
    await engine.dispose()


# Packaged Windows build only: serve the production Office UI from ROOFSPAN_STATIC_DIR (no-op in dev).
from static_serve import mount_frontend  # noqa: E402

mount_frontend(app)