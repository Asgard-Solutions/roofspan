"""Dedicated Control Plane ASGI app (production container entrypoint: `cp_app:app`).

Exposes ONLY the Control Plane router (commercial/licensing/billing/pairing/version) — NOT the customer
business routes. Fails clearly at startup if required production config is missing.
"""
from fastapi import FastAPI

from control_plane import config
from control_plane.router import router as cp_router

app = FastAPI(title="RoofSpan Control Plane", version="1")
app.include_router(cp_router)


@app.on_event("startup")
async def _startup():
    config.require_production_config()  # no-op in dev; fails clearly in production if misconfigured
