"""Control Plane models — commercial metadata only. NO customer roofing/business data here.

Distinct identifiers are preserved: company_id, installation_id, license_id are never collapsed.
The schema does not assume one company forever maps to a single installation (a company may later
have a replacement/recovery installation) — this is NOT approval for multi-company local installs or
multi-tenant business data.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Integer, BigInteger, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from control_plane.db import CPBase


def _now():
    return datetime.now(timezone.utc)


class Company(CPBase):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Installation(CPBase):
    __tablename__ = "installations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)          # installation identity public key
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # supports future key rotation
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")  # ACTIVE | REVOKED
    software_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class License(CPBase):
    __tablename__ = "licenses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False)
    installation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("installations.id"), index=True, nullable=True)
    product: Mapped[str] = mapped_column(String(64), nullable=False, default="roofspan-office")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Subscription(CPBase):
    """Normalized subscription state received from a provider-neutral billing boundary (C2 wires
    RevenueCat+Stripe to this). No card data; provider-agnostic."""
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), unique=True, index=True, nullable=False)
    license_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("licenses.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")  # ACTIVE|GRACE|SUSPENDED|CANCELLED
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    provider_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    renewal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # C2 billing-rule refinements
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # paid-through / next billing date
    pending_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)                            # scheduled seat reduction
    pending_seats_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)     # start of payment grace
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SigningKey(CPBase):
    """Ed25519 entitlement signing keys. Private PEM is stored here for DEV only (isolated CP DB);
    in production the private key lives in AWS KMS/Secrets Manager and is never in the DB/repo."""
    __tablename__ = "signing_keys"
    kid: Mapped[str] = mapped_column(String(64), primary_key=True)
    public_pem: Mapped[str] = mapped_column(Text, nullable=False)
    private_pem: Mapped[str | None] = mapped_column(Text, nullable=True)  # DEV only
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")  # ACTIVE|RETIRED|REVOKED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EntitlementIssuance(CPBase):
    __tablename__ = "entitlement_issuances"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    license_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kid: Mapped[str] = mapped_column(String(64), nullable=False)
    subscription_state: Mapped[str] = mapped_column(String(16), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="refresh")  # activation|refresh
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    refresh_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)


class VersionPolicy(CPBase):
    __tablename__ = "version_policy"
    key: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    office_latest: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    office_min_supported: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    office_recommended: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    mobile_latest: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    mobile_min_supported: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    mobile_recommended: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    office_update_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mobile_update_mandatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class RequestNonce(CPBase):
    """Replay protection for installation-authenticated requests."""
    __tablename__ = "request_nonces"
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CPAuditLog(CPBase):
    __tablename__ = "cp_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)  # installation_id | 'admin' | 'system'
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # never secrets/keys/payloads


class BillingEvent(CPBase):
    """Billing webhook idempotency + audit (Phase C2). Stores provider event metadata and the
    normalized outcome only — NEVER card data, CVV, bank credentials, or full sensitive payloads."""
    __tablename__ = "billing_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="revenuecat")
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)  # idempotency key
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    event_timestamp_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # provider event time (ordering)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")  # received|processed|ignored|error
    resulting_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    company_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)  # app_user_id (== company_id); not sensitive
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PairingToken(CPBase):
    """Short-lived, single-use Mobile pairing token (Phase C3). Contains NO secrets."""
    __tablename__ = "pairing_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    numeric_code: Mapped[str] = mapped_column(String(12), index=True, nullable=False)  # fallback code
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MobileDevice(CPBase):
    """Paired Mobile device metadata (Phase C3). NOT the employee directory (auth stays local)."""
    __tablename__ = "mobile_devices"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")  # ACTIVE | REVOKED
    paired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
