"""Centralized ABC Supply environment / URL configuration.

All ABC base URLs, OAuth endpoints, scopes and paths live here so they are never
scattered through the app. Client id/secret/redirect/webhook are per-install and
supplied at runtime (encrypted in local PostgreSQL) — never hardcoded.

The documented public base URLs (below) are NOT secrets. They can be overridden
via environment variables for testing. A local mock ABC server (see mock_server.py)
is used when ABC_MOCK_ENABLED is set, so the full flow can be exercised without real
ABC Sandbox credentials.
"""
import os
from dataclasses import dataclass

# --- Documented ABC Supply base URLs (source: https://apidocs.abcsupply.com/authorization-methods/) ---
DEFAULT_BASES = {
    "sandbox": {
        "oauth": "https://sandbox.auth.partners.abcsupply.com/oauth2/aus1vp07knpuqf6Xz0h8",
        "api": "https://partners-sb.abcsupply.com",
    },
    "production": {
        "oauth": "https://auth.partners.abcsupply.com/oauth2/ausvvp0xuwGKLenYy357",
        "api": "https://partners.abcsupply.com",
    },
}

# Documented API path prefixes (source: https://apidocs.abcsupply.com/api-endpoints/)
ACCOUNT_PREFIX = "/api/account/v1"
LOCATION_PREFIX = "/api/location/v1"
PRODUCT_PREFIX = "/api/product/v1"
PRICING_PREFIX = "/api/pricing/v2"  # verified: POST /api/pricing/v2/prices
ORDER_PREFIX = "/api/order/v2"      # verified: POST /orders, GET /orders/{orderNumber}, GET /orders?confirmationNumber=
# NEEDS ABC DOC/SANDBOX VERIFICATION: notification service path prefix (resource /webhooks only). Isolated here.
NOTIFICATION_PREFIX = "/api/notification/v1"

# Scopes (source: authorization-methods). User (auth-code) token requests offline_access to obtain a
# refresh token. Pricing is ONLY available with a user token for Third-Party Aggregators.
USER_SCOPES = (
    "account.read pricing.read order.read order.write product.read "
    "location.read notification.read notification.write offline_access"
)
# Client Credentials for Third-Party Aggregators (no pricing, no account, no order.read of user orders).
CLIENT_CREDENTIAL_SCOPES = "location.read product.read notification.read notification.write"

DEFAULT_ENVIRONMENT = "sandbox"


def mock_enabled() -> bool:
    return os.environ.get("ABC_MOCK_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _mock_internal_base() -> str:
    # Server-to-server calls loop back to this same FastAPI process where the mock is mounted.
    # The mock MUST live under /api/* because the Kubernetes ingress only routes /api/* to the backend
    # (any other path is served by the React SPA). Browser-facing OAuth URLs therefore also use /api/abc-mock.
    return os.environ.get("ABC_MOCK_INTERNAL_BASE", "http://127.0.0.1:8001").rstrip("/") + "/api/abc-mock"


@dataclass
class AbcConfig:
    environment: str
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    webhook_public_url: str | None
    oauth_base: str  # server-side OAuth base; token endpoint = oauth_base + /v1/token
    api_base: str    # server-side API base; resource paths are appended
    is_mock: bool

    @property
    def token_url(self) -> str:
        return f"{self.oauth_base}/v1/token"

    def authorize_endpoint(self, public_base: str | None = None) -> str:
        """Browser-facing authorize URL. For the mock, the browser must reach an HTTP host, so the
        caller passes the public base (its own external URL). For real ABC, the absolute Okta URL is used."""
        if self.is_mock:
            base = (public_base or _mock_internal_base()).rstrip("/")
            if base.endswith("/api/abc-mock"):
                return f"{base}/oauth2/v1/authorize"
            return f"{base}/api/abc-mock/oauth2/v1/authorize"
        return f"{self.oauth_base}/v1/authorize"


def build_config(
    *,
    environment: str | None,
    client_id: str | None,
    client_secret: str | None,
    redirect_uri: str | None,
    webhook_public_url: str | None,
) -> AbcConfig:
    env = (environment or DEFAULT_ENVIRONMENT).strip().lower()
    if env not in DEFAULT_BASES:
        env = DEFAULT_ENVIRONMENT
    is_mock = mock_enabled()
    if is_mock:
        internal = _mock_internal_base()
        oauth_base = f"{internal}/oauth2"
        api_base = internal
    else:
        oauth_base = os.environ.get("ABC_OAUTH_BASE_URL") or DEFAULT_BASES[env]["oauth"]
        api_base = os.environ.get("ABC_API_BASE_URL") or DEFAULT_BASES[env]["api"]
    return AbcConfig(
        environment=env,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        webhook_public_url=webhook_public_url,
        oauth_base=oauth_base.rstrip("/"),
        api_base=api_base.rstrip("/"),
        is_mock=is_mock,
    )
