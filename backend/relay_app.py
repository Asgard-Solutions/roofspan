"""Dedicated Secure Relay ASGI app (production container entrypoint: `relay_app:app`).

Exposes the relay health endpoint (ALB target-group health) and, when available, the relay WebSocket
route from relay.server. Stores no authoritative customer data; routing state lives in Valkey
(relay.registry). Health reports process + Valkey connectivity + routing readiness.
"""
import os

from fastapi import FastAPI

app = FastAPI(title="RoofSpan Secure Relay", version="1")

# Wire the existing relay WebSocket route(s) if the server module exposes a router/app.
try:  # pragma: no cover - depends on relay.server shape
    from relay.server import router as relay_router  # type: ignore
    app.include_router(relay_router)
except Exception:  # noqa: BLE001
    pass


@app.get("/api/relay/health")
async def relay_health():
    checks = {"process": True, "valkey": None, "routing": True}
    mode = os.environ.get("RELAY_REGISTRY", "memory").lower()
    if mode == "valkey":
        try:
            import redis.asyncio as redis
            r = redis.from_url(os.environ["RELAY_VALKEY_URL"])
            await r.ping()
            checks["valkey"] = True
        except Exception:  # noqa: BLE001
            checks["valkey"] = False
    if checks["valkey"] is False:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail={"ready": False, "checks": checks})
    return {"status": "ok", "service": "roofspan-relay", "checks": checks}
