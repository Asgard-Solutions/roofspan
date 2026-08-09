"""Configuration-driven licensing settings.

All values are environment-overridable so grace/refresh windows and mode can change
without altering the licensing architecture. Defaults match the approved Phase C0 decisions.
"""
import os

# Mode selects the Control Plane client implementation.
#   "dev"  -> in-process signing (local/dev Control Plane; no external dependency)  [Phase C0]
#   "http" -> remote Control Plane over HTTPS (Phase C1+, e.g. AWS-hosted)          [stub in C0]
LICENSING_MODE = os.environ.get("LICENSING_MODE", "dev").strip().lower()

# Timing windows (config-driven per approved decisions).
REFRESH_INTERVAL_HOURS = float(os.environ.get("LICENSING_REFRESH_HOURS", "12"))
OFFLINE_GRACE_DAYS = float(os.environ.get("LICENSING_OFFLINE_GRACE_DAYS", "7"))
PAYMENT_GRACE_DAYS = float(os.environ.get("LICENSING_PAYMENT_GRACE_DAYS", "14"))

# Seat bounds are product-locked (not pricing). Do NOT hardcode pricing anywhere.
MIN_SEATS = int(os.environ.get("LICENSING_MIN_SEATS", "5"))
MAX_SEATS = int(os.environ.get("LICENSING_MAX_SEATS", "50"))

PRODUCT = os.environ.get("LICENSING_PRODUCT", "roofspan-office")
MIN_SUPPORTED_VERSION = os.environ.get("ROOFSPAN_MIN_VERSION", "1.0.0")

# In-memory effective-state snapshot TTL (seconds). Keeps entitlement checks off the
# Control Plane and off the hot DB path for the guard middleware.
STATE_SNAPSHOT_TTL_SECONDS = float(os.environ.get("LICENSING_SNAPSHOT_TTL", "30"))

# ---- DEV signing (Phase C0 only) ------------------------------------------------
# Development/test signing keys are generated locally and live ONLY in this directory.
# They are git-ignored. Production entitlement signing happens on the Control Plane with
# a private key that MUST NEVER be placed in a customer installation or this repository.
DEV_KEYS_DIR = os.environ.get(
    "LICENSING_DEV_KEYS_DIR", os.path.join(os.path.dirname(__file__), "dev_keys")
)
DEV_KID = os.environ.get("LICENSING_DEV_KID", "dev-ed25519-1")

# Dev default entitlement so an existing running installation is unaffected by the new
# licensing layer. Production seat counts come from the signed entitlement (5..50).
DEV_DEFAULT_STATE = os.environ.get("LICENSING_DEV_STATE", "ACTIVE")
DEV_DEFAULT_SEATS = int(os.environ.get("LICENSING_DEV_SEATS", str(MAX_SEATS)))

# ---- HTTP Control Plane (Phase C1+) --------------------------------------------
CONTROL_PLANE_URL = os.environ.get("LICENSING_CONTROL_PLANE_URL")  # None in C0; set for http mode

# DEV activation bootstrap credential (installer/first-run). Isolated dev mechanism; production
# activation credential/checkout linkage is finalized with C2 billing. Never a long-lived master
# credential embedded in the installer.
ACTIVATION_BOOTSTRAP_CREDENTIAL = os.environ.get("LICENSING_ACTIVATION_CREDENTIAL", "dev-bootstrap-roofspan")
ACTIVATION_COMPANY_NAME = os.environ.get("LICENSING_ACTIVATION_COMPANY", "RoofSpan Roofing Co.")
ACTIVATION_REQUESTED_SEATS = int(os.environ.get("LICENSING_ACTIVATION_SEATS", str(MIN_SEATS)))
SOFTWARE_VERSION = os.environ.get("ROOFSPAN_VERSION", "1.0.0")

# Trusted Control-Plane entitlement verification public keys are cached here (written by the http
# client after activation/refresh). In production these are baked into the release + refreshable.
TRUSTED_KEYS_DIR = os.environ.get(
    "LICENSING_TRUSTED_KEYS_DIR", os.path.join(os.path.dirname(__file__), "trusted_keys")
)
