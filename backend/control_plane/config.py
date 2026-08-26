"""Control Plane configuration (deployment-neutral, config-driven)."""
import os

from urllib.parse import urlparse, urlunparse


def _to_async_url(url: str) -> str:
    """Force the SQLAlchemy async driver (asyncpg).

    Managed providers hand out plain ``postgresql://`` URLs. Passed to ``create_async_engine`` those
    default to a synchronous dialect, while the rest of the CP package deliberately converts away
    from ``+asyncpg`` for its synchronous psycopg work. ``+asyncpg`` is the canonical runtime form.
    """
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme in (
        "postgres",
        "postgresql",
        "postgresql+psycopg2",
        "postgresql+psycopg",
        "postgresql+asyncpg",
    ):
        parsed = parsed._replace(scheme="postgresql+asyncpg")
    return urlunparse(parsed)


def _derive_cp_url() -> str:
    """Default the Control Plane DB to a separate DB on the same server as the business DB."""
    explicit = os.environ.get("CONTROL_PLANE_DATABASE_URL")
    if explicit:
        return _to_async_url(explicit)
    base = os.environ.get("DATABASE_URL")
    if not base:
        return ""
    parsed = urlparse(base)
    new = parsed._replace(path="/roofspan_control_plane")
    return _to_async_url(urlunparse(new))


CONTROL_PLANE_DATABASE_URL = _derive_cp_url()
CONTROL_PLANE_SCHEMA = os.environ.get("CONTROL_PLANE_SCHEMA", "").strip() or None

REQUEST_TIMESTAMP_TOLERANCE = int(os.environ.get("CP_REQUEST_TIMESTAMP_TOLERANCE", "300"))
NONCE_RETENTION_SECONDS = int(os.environ.get("CP_NONCE_RETENTION_SECONDS", "900"))
DEV_BOOTSTRAP_SECRET = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")
DEV_ADMIN_SECRET = os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")
MIN_SEATS = int(os.environ.get("LICENSING_MIN_SEATS", "5"))
MAX_SEATS = int(os.environ.get("LICENSING_MAX_SEATS", "50"))
PRODUCT = os.environ.get("LICENSING_PRODUCT", "roofspan-office")
REFRESH_INTERVAL_HOURS = float(os.environ.get("LICENSING_REFRESH_HOURS", "12"))
OFFLINE_GRACE_DAYS = float(os.environ.get("LICENSING_OFFLINE_GRACE_DAYS", "7"))
PAYMENT_GRACE_DAYS = float(os.environ.get("LICENSING_PAYMENT_GRACE_DAYS", "7"))
BILLING_PERIOD_DAYS = int(os.environ.get("BILLING_PERIOD_DAYS", "30"))

DEV_SIGNING_KEYS_DIR = os.environ.get(
    "CP_DEV_SIGNING_KEYS_DIR", os.path.join(os.path.dirname(__file__), "dev_signing_keys")
)

MIN_SUPPORTED_VERSION = os.environ.get("ROOFSPAN_MIN_VERSION", "1.0.0")
# Pairing responses must direct Mobile to the public Relay, never the Office localhost CP. Accept the
# explicit CP variable first, then the shared production Relay setting used by the Windows connector.
RELAY_ENDPOINT = (
    os.environ.get("ROOFSPAN_RELAY_ENDPOINT")
    or os.environ.get("RELAY_WSS_URL")
    or "wss://relay.roofspan.io"
).strip().rstrip("/")
PROTOCOL_VERSION = os.environ.get("ROOFSPAN_PROTOCOL_VERSION", "1")
PAIRING_TTL_SECONDS = int(os.environ.get("PAIRING_TTL_SECONDS", "300"))
BILLING_MODE = os.environ.get("BILLING_MODE", "mock").strip().lower()
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SEAT_LOOKUP_KEY = os.environ.get("STRIPE_SEAT_LOOKUP_KEY", "roofspan_seat_monthly")
SEAT_PRICE_USD = float(os.environ.get("ROOFSPAN_SEAT_PRICE_USD", "49"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")
CP_ENV = os.environ.get("CP_ENV", "dev").strip().lower()
ENTITLEMENT_SIGNER = os.environ.get(
    "ENTITLEMENT_SIGNER", "local" if CP_ENV != "production" else "kms"
).strip().lower()
CP_KMS_SIGNING_KEY_ID = os.environ.get("CP_KMS_SIGNING_KEY_ID", "")
AWS_REGION = os.environ.get("AWS_REGION", "")
CP_OPERATOR_ISSUER = os.environ.get("CP_OPERATOR_ISSUER", "")
CP_OPERATOR_AUDIENCE = os.environ.get("CP_OPERATOR_AUDIENCE", "")


def require_production_config() -> None:
    if CP_ENV != "production":
        return
    missing = []
    if BILLING_MODE != "stripe" or not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        missing.append("Stripe (BILLING_MODE=stripe + STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET)")
    if ENTITLEMENT_SIGNER == "kms" and not CP_KMS_SIGNING_KEY_ID:
        missing.append("CP_KMS_SIGNING_KEY_ID (KMS entitlement signer)")
    if not (CP_OPERATOR_ISSUER and CP_OPERATOR_AUDIENCE):
        missing.append("CP_OPERATOR_ISSUER + CP_OPERATOR_AUDIENCE (operator auth)")
    if missing:
        raise RuntimeError("RoofSpan Control Plane production config missing: " + "; ".join(missing))
