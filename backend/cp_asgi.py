"""Railway / production ASGI entrypoint for the RoofSpan CENTRAL Control Plane ONLY.

This exposes just the Control Plane API (installation activation, signed entitlements, licensing/
subscription state, Stripe Checkout creation + webhook reconciliation, seat licensing, version policy,
pairing/relay metadata) plus a Railway health endpoint. It deliberately does NOT mount the RoofSpan Office
customer application surface (leads/jobs/inventory/etc.) and stores NO customer business data - that lives
locally in each customer's PostgreSQL install.

Start (Railway injects $PORT):
    uvicorn cp_asgi:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import logging
import sys

from fastapi import FastAPI

from control_plane import config as cp_config
from control_plane.router import router as control_plane_router
from control_plane.service import init_control_plane

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,  # Railway captures stdout/stderr
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("roofspan.cp")

app = FastAPI(
    title="RoofSpan Control Plane",
    version="1.0.0",
    docs_url=None,      # no public API docs surface in production
    redoc_url=None,
    openapi_url=None,
)
app.include_router(control_plane_router)


@app.get("/health")
async def health():
    """Railway health check. Always reports the web process is alive; best-effort DB probe (never
    leaks connection strings / secrets / stack traces)."""
    db_ok = None
    try:
        from control_plane.db import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = "ok"
    except Exception:  # noqa: BLE001 - health must not raise or leak details
        db_ok = "unavailable"
    return {"status": "ok", "service": "control-plane", "env": cp_config.CP_ENV, "database": db_ok}


@app.on_event("startup")
async def _startup():
    # Fail CLOSED before serving if production config is incomplete (no silent dev/mock/local fallback).
    cp_config.require_production_config()
    logger.info("Control Plane starting (CP_ENV=%s, signer=%s)", cp_config.CP_ENV, cp_config.ENTITLEMENT_SIGNER)

    # Railway may start this service before Postgres is reachable. Bounded retry (never an infinite loop):
    # migrations + signing-key + version-policy bootstrap via the existing idempotent init_control_plane().
    attempts = int(__import__("os").environ.get("CP_DB_INIT_MAX_ATTEMPTS", "12"))
    delay = 5
    for attempt in range(1, attempts + 1):
        try:
            await init_control_plane()
            logger.info("Control Plane schema ready (migrations applied).")
            return
        except Exception as e:  # noqa: BLE001
            if attempt >= attempts:
                logger.error("Control Plane DB init failed after %d attempts: %s", attempts, type(e).__name__)
                raise
            logger.warning("Control Plane DB not ready (attempt %d/%d); retrying in %ds", attempt, attempts, delay)
            await asyncio.sleep(delay)
