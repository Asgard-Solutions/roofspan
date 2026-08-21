"""Railway / production ASGI entrypoint for the RoofSpan CENTRAL Control Plane ONLY.

This exposes just the Control Plane API (installation activation, signed entitlements, licensing/
subscription state, Stripe Checkout creation + webhook reconciliation, seat licensing, version policy,
pairing/relay metadata) plus Railway health/readiness endpoints. It deliberately does NOT mount the
RoofSpan Office customer application surface (leads/jobs/inventory/etc.) and stores NO customer business
data - that lives locally in each customer's PostgreSQL install.

Start (Railway injects $PORT):
    uvicorn cp_asgi:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.responses import JSONResponse

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

_db_init_ready = False
_db_init_error: str | None = None
_db_init_task: asyncio.Task | None = None


@app.get("/health")
async def health():
    """Liveness endpoint used by Railway.

    This intentionally does not block deployment on Postgres migrations or KMS/bootstrap work. If the
    web process is accepting HTTP, Railway should consider the container alive. Database readiness is
    exposed separately at /ready.
    """
    return {"status": "ok", "service": "control-plane", "env": cp_config.CP_ENV}


@app.get("/ready")
async def ready():
    """Readiness endpoint for operators. Returns 503 until Control Plane DB/bootstrap init completes."""
    if _db_init_ready:
        return {"status": "ok", "service": "control-plane", "database": "ready"}

    detail = "initializing" if _db_init_error is None else "initialization_failed"
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "service": "control-plane", "database": detail},
    )


async def _initialize_control_plane_background() -> None:
    """Initialize DB/schema without holding Railway's liveness check hostage."""
    global _db_init_ready, _db_init_error

    attempts = int(os.environ.get("CP_DB_INIT_MAX_ATTEMPTS", "12"))
    delay = int(os.environ.get("CP_DB_INIT_RETRY_DELAY_SECONDS", "5"))

    for attempt in range(1, attempts + 1):
        try:
            await init_control_plane()
            _db_init_ready = True
            _db_init_error = None
            logger.info("Control Plane schema ready (migrations applied).")
            return
        except Exception as e:  # noqa: BLE001
            _db_init_ready = False
            _db_init_error = type(e).__name__
            if attempt >= attempts:
                logger.exception(
                    "Control Plane DB init failed after %d attempts; process remains alive for diagnostics",
                    attempts,
                )
                return
            logger.warning(
                "Control Plane DB not ready (attempt %d/%d, %s); retrying in %ds",
                attempt,
                attempts,
                type(e).__name__,
                delay,
            )
            await asyncio.sleep(delay)


@app.on_event("startup")
async def _startup():
    global _db_init_task

    # Still fail closed for incomplete production secrets/config. The change below only separates
    # container liveness from database/bootstrap readiness.
    cp_config.require_production_config()
    logger.info("Control Plane starting (CP_ENV=%s, signer=%s)", cp_config.CP_ENV, cp_config.ENTITLEMENT_SIGNER)

    # Do not await migrations here. Awaiting them prevents Uvicorn from accepting /health requests,
    # causing Railway to kill an otherwise-running container before DB initialization can finish.
    _db_init_task = asyncio.create_task(_initialize_control_plane_background())


@app.on_event("shutdown")
async def _shutdown():
    if _db_init_task is not None and not _db_init_task.done():
        _db_init_task.cancel()
        try:
            await _db_init_task
        except asyncio.CancelledError:
            pass
