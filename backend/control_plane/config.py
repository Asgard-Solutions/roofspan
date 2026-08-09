"""Control Plane configuration (deployment-neutral, config-driven)."""
import os

from urllib.parse import urlparse, urlunparse


def _derive_cp_url() -> str:
    """Default the Control Plane DB to a SEPARATE database on the same server as the business DB.

    This keeps commercial metadata physically separate from customer business data and keeps the
    business Alembic autogenerate clean (CP tables live in a different database).
    """
    explicit = os.environ.get("CONTROL_PLANE_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base:
        return ""
    parsed = urlparse(base)
    # replace the path (database name) with the control-plane database
    new = parsed._replace(path="/roofspan_control_plane")
    return urlunparse(new)


CONTROL_PLANE_DATABASE_URL = _derive_cp_url()

# Timestamp tolerance (seconds) for installation-authenticated requests (replay window).
REQUEST_TIMESTAMP_TOLERANCE = int(os.environ.get("CP_REQUEST_TIMESTAMP_TOLERANCE", "300"))
# How long a used nonce is remembered (>= tolerance so replays inside the window are caught).
NONCE_RETENTION_SECONDS = int(os.environ.get("CP_NONCE_RETENTION_SECONDS", "900"))

# DEV bootstrap credential for activation. Clearly isolated dev mechanism; production activation
# credential/checkout linkage is finalized with C2 billing. Never a long-lived master credential in
# the installer.
DEV_BOOTSTRAP_SECRET = os.environ.get("CP_DEV_BOOTSTRAP_SECRET", "dev-bootstrap-roofspan")

# DEV admin credential guarding Control Plane admin/dev endpoints (revoke, key rotation, subscription
# updates, version policy writes). Production uses proper operator auth (HUMAN REQUIRED).
DEV_ADMIN_SECRET = os.environ.get("CP_DEV_ADMIN_SECRET", "dev-admin-roofspan")

# Seat bounds (mirror licensing.config; product-locked, not pricing).
MIN_SEATS = int(os.environ.get("LICENSING_MIN_SEATS", "5"))
MAX_SEATS = int(os.environ.get("LICENSING_MAX_SEATS", "50"))
PRODUCT = os.environ.get("LICENSING_PRODUCT", "roofspan-office")

# Entitlement timing (mirror licensing.config so policy is not duplicated divergently).
REFRESH_INTERVAL_HOURS = float(os.environ.get("LICENSING_REFRESH_HOURS", "12"))
OFFLINE_GRACE_DAYS = float(os.environ.get("LICENSING_OFFLINE_GRACE_DAYS", "7"))

# DEV signing-key storage dir (git-ignored). Production signing keys live in AWS KMS/Secrets Manager
# (HUMAN REQUIRED) — never in the repo or ordinary config.
DEV_SIGNING_KEYS_DIR = os.environ.get(
    "CP_DEV_SIGNING_KEYS_DIR", os.path.join(os.path.dirname(__file__), "dev_signing_keys")
)

MIN_SUPPORTED_VERSION = os.environ.get("ROOFSPAN_MIN_VERSION", "1.0.0")
