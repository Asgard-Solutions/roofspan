"""Control Plane billing adapters (Phase C2) behind the provider-neutral BillingProvider contract.

RevenueCat + Stripe is the first provider. Provider-specific strings never leak past this module:
everything is normalized to RoofSpan states (ACTIVE/GRACE/SUSPENDED/CANCELLED) here. Helcim can be
added later by implementing the same interface. No raw card data is ever handled or stored.

DEV: `mock` provider (default) makes the webhook/checkout/portal flow testable with no external
account. `revenuecat` provider requires HUMAN REQUIRED credentials (see config).
"""
from __future__ import annotations

import os
import hmac
from dataclasses import dataclass
from urllib.parse import quote

# RoofSpan normalized states
ACTIVE, GRACE, SUSPENDED, CANCELLED = "ACTIVE", "GRACE", "SUSPENDED", "CANCELLED"

BILLING_MODE = os.environ.get("BILLING_MODE", "mock").strip().lower()  # mock | revenuecat | stub

# ---- HUMAN REQUIRED (RevenueCat) — dev placeholders; never commit real secrets ----
REVENUECAT_API_BASE = os.environ.get("REVENUECAT_API_BASE", "https://api.revenuecat.com/v1")
REVENUECAT_SECRET_API_KEY = os.environ.get("REVENUECAT_SECRET_API_KEY", "")
REVENUECAT_APP_ID = os.environ.get("REVENUECAT_APP_ID", "")
REVENUECAT_WEBHOOK_AUTH = os.environ.get("REVENUECAT_WEBHOOK_AUTH", "dev-webhook-secret")
REVENUECAT_PURCHASE_LINK = os.environ.get("REVENUECAT_PURCHASE_LINK", "https://pay.rev.cat/DEV_PLACEHOLDER")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")

# RevenueCat event type -> normalized RoofSpan state (None = record only, no state change).
# Note: CANCELLATION (auto-renew off) does NOT immediately block — access continues until EXPIRATION.
EVENT_STATE_MAP = {
    "INITIAL_PURCHASE": ACTIVE,
    "RENEWAL": ACTIVE,
    "UNCANCELLATION": ACTIVE,
    "PRODUCT_CHANGE": ACTIVE,
    "NON_RENEWING_PURCHASE": ACTIVE,
    "BILLING_ISSUE": GRACE,
    "SUBSCRIPTION_PAUSED": GRACE,
    "EXPIRATION": SUSPENDED,
    "CANCELLATION": None,  # recorded; no immediate state change (see DECISION REQUIRED)
}


@dataclass
class ParsedWebhook:
    event_id: str
    event_type: str
    company_reference: str | None   # app_user_id (== company_id); not sensitive
    timestamp_ms: int | None
    normalized_state: str | None


class BillingAuthError(Exception):
    pass


class BillingProvider:
    name = "base"

    def verify_and_parse_webhook(self, headers: dict, body: bytes, payload: dict) -> ParsedWebhook: ...
    def checkout_url(self, company_id: str) -> str: ...
    async def portal_url(self, company_id: str) -> str | None: ...
    async def reconcile(self, company_id: str) -> dict: ...


class MockBillingProvider(BillingProvider):
    name = "mock"

    def verify_and_parse_webhook(self, headers, body, payload):
        auth = headers.get("authorization") or headers.get("Authorization")
        if not auth or not hmac.compare_digest(auth, REVENUECAT_WEBHOOK_AUTH):
            raise BillingAuthError("invalid webhook authorization")
        ev = payload.get("event", {})
        etype = ev.get("type", "")
        return ParsedWebhook(
            event_id=ev.get("id", ""), event_type=etype,
            company_reference=ev.get("app_user_id"),
            timestamp_ms=ev.get("event_timestamp_ms"),
            normalized_state=EVENT_STATE_MAP.get(etype),
        )

    def checkout_url(self, company_id: str) -> str:
        return f"{APP_BASE_URL}/mock-checkout?app_user_id={quote(company_id)}"

    async def portal_url(self, company_id: str) -> str | None:
        return f"{APP_BASE_URL}/mock-portal?app_user_id={quote(company_id)}"

    async def reconcile(self, company_id: str) -> dict:
        # Mock: reports ACTIVE. Real reconcile derives from provider REST.
        return {"state": ACTIVE, "seats": None}


class RevenueCatStripeProvider(BillingProvider):
    name = "revenuecat"

    def verify_and_parse_webhook(self, headers, body, payload):
        auth = headers.get("authorization") or headers.get("Authorization")
        if not auth or not hmac.compare_digest(auth, REVENUECAT_WEBHOOK_AUTH):
            raise BillingAuthError("invalid webhook authorization")
        if payload.get("api_version") not in ("1.0", None):
            raise BillingAuthError("unsupported webhook api_version")
        ev = payload.get("event", {})
        if REVENUECAT_APP_ID and ev.get("app_id") not in (REVENUECAT_APP_ID, None):
            raise BillingAuthError("webhook app_id mismatch")
        etype = ev.get("type", "")
        return ParsedWebhook(
            event_id=ev.get("id", ""), event_type=etype,
            company_reference=ev.get("app_user_id"),
            timestamp_ms=ev.get("event_timestamp_ms"),
            normalized_state=EVENT_STATE_MAP.get(etype),
        )

    def checkout_url(self, company_id: str) -> str:
        # Hosted RevenueCat Web Purchase Link with URL-encoded app_user_id.
        return f"{REVENUECAT_PURCHASE_LINK.rstrip('/')}/{quote(company_id, safe='')}"

    async def reconcile(self, company_id: str) -> dict:
        import httpx
        if not REVENUECAT_SECRET_API_KEY:
            raise BillingAuthError("RevenueCat secret API key not configured")
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{REVENUECAT_API_BASE}/subscribers/{quote(company_id, safe='')}",
                            headers={"Authorization": f"Bearer {REVENUECAT_SECRET_API_KEY}"})
            r.raise_for_status()
            data = r.json()
        active = data.get("subscriber", {}).get("entitlements", {}).get("active", {})
        return {"state": ACTIVE if active else SUSPENDED, "seats": None,
                "management_url": data.get("subscriber", {}).get("management_url")}

    async def portal_url(self, company_id: str) -> str | None:
        return (await self.reconcile(company_id)).get("management_url")


class StubBillingProvider(BillingProvider):
    name = "stub"

    def verify_and_parse_webhook(self, headers, body, payload):
        raise BillingAuthError("billing provider not configured")

    def checkout_url(self, company_id: str) -> str:
        raise BillingAuthError("billing provider not configured")

    async def portal_url(self, company_id: str) -> str | None:
        raise BillingAuthError("billing provider not configured")

    async def reconcile(self, company_id: str) -> dict:
        raise BillingAuthError("billing provider not configured")


def get_provider() -> BillingProvider:
    if BILLING_MODE == "revenuecat":
        return RevenueCatStripeProvider()
    if BILLING_MODE == "stub":
        return StubBillingProvider()
    return MockBillingProvider()
