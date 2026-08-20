"""Configuration-driven licensing settings.

All values are environment-overridable so grace/refresh windows and mode can change
without altering the licensing architecture. Defaults match the approved Phase C0 decisions.
"""
import os

# Mode selects the Control Plane client implementation.
#   "dev"  -> in-process signing (local/dev Control Plane; no external dependency)  [Phase C0]
#   "http" -> remote Control Plane over HTTPS (Phase C1+, e.g. AWS-hosted)
LICENSING_MODE = os.environ.get("LICENSING_MODE", "dev").strip().lower()

# Timing windows (config-driven per approved decisions).
REFRESH_INTERVAL_HOURS = float(os.environ.get("LICENSING_REFRESH_HOURS", "12"))
OFFLINE_GRACE_DAYS = float(os.environ.get("LICENSING_OFFLINE_GRACE_DAYS", "7"))
PAYMENT_GRACE_DAYS = float(os.environ.get("LICENSING_PAYMENT_GRACE_DAYS", "7"))

# Seat bounds are product-locked (not pricing). Do NOT hardcode pricing anywhere.
MIN_SEATS = int(os.environ.get("LICENSING_MIN_SEATS", "5"))
MAX_SEATS = int(os.environ.get("LICENSING_MAX_SEATS", "50"))

PRODUCT = os.environ.get("LICENSING_PRODUCT", "roofspan-office")
MIN_SUPPORTED_VERSION = os.environ.get("ROOFSPAN_MIN_VERSION", "1.0.0")
MIN_MOBILE_VERSION = os.environ.get("ROOFSPAN_MIN_MOBILE_VERSION", "1.0.0")
STATE_SNAPSHOT_TTL_SECONDS = float(os.environ.get("LICENSING_SNAPSHOT_TTL", "30"))

# Persist local licensing key material outside the installed application directory whenever
# ROOFSPAN_DATA_ROOT is available (Windows service sets this to C:\ProgramData\RoofSpan).
# This prevents upgrades/reinstalls from silently replacing the dev verification key and making
# an otherwise-valid cached entitlement unverifiable.
_data_root = os.environ.get("ROOFSPAN_DATA_ROOT", "").strip()
_default_dev_keys_dir = (
    os.path.join(_data_root, "identity", "licensing-dev-keys")
    if _data_root else os.path.join(os.path.dirname(__file__), "dev_keys")
)
_default_trusted_keys_dir = (
    os.path.join(_data_root, "identity", "licensing-trusted-keys")
    if _data_root else os.path.join(os.path.dirname(__file__), "trusted_keys")
)

DEV_KEYS_DIR = os.environ.get("LICENSING_DEV_KEYS_DIR", _default_dev_keys_dir)
DEV_KID = os.environ.get("LICENSING_DEV_KID", "dev-ed25519-1")

DEV_DEFAULT_STATE = os.environ.get("LICENSING_DEV_STATE", "ACTIVE")
DEV_DEFAULT_SEATS = int(os.environ.get("LICENSING_DEV_SEATS", "1000"))

CONTROL_PLANE_URL = os.environ.get("LICENSING_CONTROL_PLANE_URL")

ACTIVATION_BOOTSTRAP_CREDENTIAL = os.environ.get("LICENSING_ACTIVATION_CREDENTIAL", "dev-bootstrap-roofspan")
ACTIVATION_COMPANY_NAME = os.environ.get("LICENSING_ACTIVATION_COMPANY", "RoofSpan Roofing Co.")
ACTIVATION_REQUESTED_SEATS = int(os.environ.get("LICENSING_ACTIVATION_SEATS", str(MIN_SEATS)))
SOFTWARE_VERSION = os.environ.get("ROOFSPAN_VERSION", "1.0.0")

TRUSTED_KEYS_DIR = os.environ.get("LICENSING_TRUSTED_KEYS_DIR", _default_trusted_keys_dir)
