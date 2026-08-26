"""Railway ASGI entrypoint for RoofSpan central services.

The Control Plane and Secure Relay are hosted together initially so Office pairing, installation
identity authentication, and Mobile routing share one authoritative commercial-metadata database.
Customer Office workflows and roofing-business data remain local to each Windows installation.
``cp.roofspan.io`` and ``relay.roofspan.io`` may point at this same service; their public responsibilities
remain logically separate even while deployed in one small process.
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
from control_plane.installation_router import router as control_plane_installation_router
from control_plane.router import router as control_plane_router
from relay import config as relay_config
from relay.hub import hub as relay_hub
from relay.server import router as relay_router

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("roofspan.cloud")

app = FastAPI(
    title="RoofSpan Central Services",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(control_plane_router)
app.include_router(control_plane_installation_router)
app.include_router(relay_router)

_db_init_task: asyncio.Task | None = None


@app.get("/health")
async def health():
    """Process liveness. Database/bootstrap readiness is reported separately at /ready."""
    status = cp_readiness.snapshot()
    return {
        "status": "ok",
        "service": "roofspan-central",
        "env": cp_config.CP_ENV,
        "control_plane": {
            "ready": status["ready"],
            "state": status["state"],
            "code": status["code"],
        },
        "relay": {
            "env": relay_config.RELAY_ENV,
            "registry": relay_config.RELAY_REGISTRY,
            "node_id": relay_config.NODE_ID,
        },
    }


@app.get("/ready")
async def ready():
    status = cp_readiness.snapshot()
    return JSONResponse(status_code=200 if status["ready"] else 503, content=status)


async def _initialize_control_plane_background() -> None:
    """Initialize DB/schema without holding liveness checks hostage."""
    attempts = int(os.environ.get("CP_DB_INIT_MAX_ATTEMPTS", "12"))
    delay = int(os.environ.get("CP_DB_INIT_RETRY_DELAY_SECONDS", "5"))

    for attempt in range(1, attempts + 1):
        try:
            await init_control_plane()
            logger.info("Control Plane schema/readiness initialized; Relay authentication is available.")
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
    # Single-node memory mode is valid for the initial one-instance deployment. When RELAY_ENV is
    # explicitly set to production, enforce the existing Valkey + stable-node-id contract.
    relay_config.require_production_config()
    await relay_hub.startup()
    logger.info(
        "RoofSpan central services starting (CP_ENV=%s, signer=%s, relay=%s/%s)",
        cp_config.CP_ENV,
        cp_config.ENTITLEMENT_SIGNER,
        relay_config.RELAY_ENV,
        relay_config.RELAY_REGISTRY,
    )
    _db_init_task = asyncio.create_task(_initialize_control_plane_background())


@app.on_event("shutdown")
async def _shutdown():
    if _db_init_task is not None and not _db_init_task.done():
        _db_init_task.cancel()
        try:
            await _db_init_task
        except asyncio.CancelledError:
            pass
    await relay_hub.shutdown()
