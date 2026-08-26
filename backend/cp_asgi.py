"""Railway / production ASGI entrypoint for the RoofSpan CENTRAL Control Plane ONLY.

This exposes just the Control Plane API plus liveness/readiness endpoints. Customer business data and
Office workflows remain local to each customer's installation.
"""
import asyncio
import logging
import os
import sys

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from control_plane import config as cp_config
from control_plane import readiness as cp_readiness
from control_plane.bootstrap import init_control_plane
from control_plane.router import router as control_plane_router

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("roofspan.cp")

app = FastAPI(
    title="RoofSpan Control Plane",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(control_plane_router)

_db_init_task: asyncio.Task | None = None


@app.get("/health")
async def health():
    """Process liveness. Database/bootstrap readiness is reported separately at /ready."""
    status = cp_readiness.snapshot()
    return {
        "status": "ok",
        "service": "control-plane",
        "env": cp_config.CP_ENV,
        "control_plane": {"ready": status["ready"], "state": status["state"], "code": status["code"]},
    }


@app.get("/ready")
async def ready():
    status = cp_readiness.snapshot()
    return JSONResponse(status_code=200 if status["ready"] else 503, content=status)


async def _initialize_control_plane_background() -> None:
    """Initialize DB/schema without holding Railway's liveness check hostage."""
    attempts = int(os.environ.get("CP_DB_INIT_MAX_ATTEMPTS", "12"))
    delay = int(os.environ.get("CP_DB_INIT_RETRY_DELAY_SECONDS", "5"))

    for attempt in range(1, attempts + 1):
        try:
            await init_control_plane()
            logger.info("Control Plane schema and readiness gate initialized.")
            return
        except Exception as exc:  # noqa: BLE001
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
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)


@app.on_event("startup")
async def _startup():
    global _db_init_task

    cp_config.require_production_config()
    logger.info("Control Plane starting (CP_ENV=%s, signer=%s)", cp_config.CP_ENV, cp_config.ENTITLEMENT_SIGNER)
    _db_init_task = asyncio.create_task(_initialize_control_plane_background())


@app.on_event("shutdown")
async def _shutdown():
    if _db_init_task is not None and not _db_init_task.done():
        _db_init_task.cancel()
        try:
            await _db_init_task
        except asyncio.CancelledError:
            pass
