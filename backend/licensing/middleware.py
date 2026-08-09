"""Subscription guard middleware.

Blocks normal business API workflows when the installation is SUSPENDED/CANCELLED (or offline grace
exhausted). Owner/Admin can still authenticate and reach subscription/license/billing/recovery
endpoints. Reads a short-lived in-process snapshot — no Control Plane call and no DB hit on the hot
path beyond one lightweight query per snapshot TTL.
"""
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from licensing import service
from licensing.state import BUSINESS_ALLOWED

logger = logging.getLogger("roofspan")

# Always-allowed API prefixes (auth + licensing/billing/recovery + health + dev tooling).
_ALLOWLIST = (
    "/api/health",
    "/api/auth",
    "/api/subscription",
    "/api/license",
    "/api/billing",
    "/api/dev/",
)


def _is_guarded(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return False
    if not path.startswith("/api/"):
        return False  # frontend + non-API assets pass through
    return not any(path.startswith(p) for p in _ALLOWLIST)


class SubscriptionGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if _is_guarded(request.url.path, request.method):
            try:
                state = await service.effective_state_cached()
            except Exception as e:  # never hard-fail a request because the guard errored
                logger.warning("Subscription guard check failed (allowing request): %s", e)
                state = None
            if state is not None and state not in BUSINESS_ALLOWED:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Your RoofSpan subscription requires attention. Your company data is safe, "
                                  "but normal RoofSpan functionality is temporarily unavailable. Update your "
                                  "billing information to restore access.",
                        "code": "subscription_inactive",
                        "state": state,
                    },
                )
        return await call_next(request)
