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
    # Stripe-enriched optional fields (None for RevenueCat/mock — behavior unchanged there):
    seats: int | None = None
    current_period_end: object | None = None          # datetime
    cancel_at_period_end: bool | None = None
    provider_subscription_id: str | None = None
    provider_customer_id: str | None = None
    raw_object: dict | None = None


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


# ---- Stripe Billing (authoritative subscription/payment engine) ----

import datetime as _dt  # noqa: E402

from control_plane import config as _cpc  # noqa: E402

# Stripe subscription.status -> RoofSpan normalized state.
_STRIPE_STATUS_MAP = {
    "active": ACTIVE, "trialing": ACTIVE,
    "past_due": GRACE,
    "unpaid": SUSPENDED, "incomplete_expired": SUSPENDED,
    "canceled": CANCELLED,
    "incomplete": None, "paused": GRACE,
}


def _ts_to_dt(ts):
    return _dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc) if ts else None


class StripeBillingProvider(BillingProvider):
    """Direct Stripe Billing engine. Seat count == subscription item quantity ($49/seat/month).

    No card data ever handled or stored. All provider strings normalized to RoofSpan states here.
    """
    name = "stripe"

    def __init__(self):
        import stripe
        if not _cpc.STRIPE_SECRET_KEY:
            raise BillingAuthError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
        self.stripe = stripe
        stripe.api_key = _cpc.STRIPE_SECRET_KEY
        self.webhook_secret = _cpc.STRIPE_WEBHOOK_SECRET
        self.lookup_key = _cpc.STRIPE_SEAT_LOOKUP_KEY

    # -- price / subscription helpers --
    def _seat_price_id(self) -> str:
        prices = self.stripe.Price.list(lookup_keys=[self.lookup_key], active=True, limit=1).data
        if not prices:
            raise BillingAuthError(f"Stripe seat price not found (lookup_key={self.lookup_key}); run setup_stripe.py")
        return prices[0].id

    def _clamp(self, seats: int) -> int:
        return max(_cpc.MIN_SEATS, min(_cpc.MAX_SEATS, int(seats)))

    def retrieve_subscription(self, subscription_id: str):
        return self.stripe.Subscription.retrieve(subscription_id, expand=["items"])

    def normalize_subscription(self, sub) -> dict:
        d = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
        item = (d.get("items", {}).get("data") or [{}])[0]
        seats = item.get("quantity")
        state = _STRIPE_STATUS_MAP.get(d.get("status"))
        return {
            "state": state,
            "seats": self._clamp(seats) if seats else None,
            "current_period_end": _ts_to_dt(d.get("current_period_end") or item.get("current_period_end")),
            "cancel_at_period_end": bool(d.get("cancel_at_period_end")),
            "provider_subscription_id": d.get("id"),
            "provider_customer_id": d.get("customer"),
            "company_reference": (d.get("metadata") or {}).get("company_id"),
        }

    # -- checkout / lifecycle --
    def create_checkout_session(self, company_id: str, seats: int, origin_url: str | None = None) -> str:
        seats = self._clamp(seats)
        origin = (origin_url or _cpc.APP_BASE_URL).rstrip("/")
        session = self.stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": self._seat_price_id(), "quantity": seats}],
            client_reference_id=company_id,
            subscription_data={"metadata": {"company_id": company_id}},
            metadata={"company_id": company_id},
            success_url=f"{origin}/admin/subscription?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/admin/subscription?checkout=cancel",
        )
        return session.url

    def checkout_url(self, company_id: str) -> str:
        # Initial purchase with the RoofSpan minimum of 5 seats.
        return self.create_checkout_session(company_id, _cpc.MIN_SEATS)

    def update_seats(self, subscription_id: str, seats: int) -> dict:
        """Increase = immediate with proration; decrease = scheduled at next renewal via a Schedule."""
        seats = self._clamp(seats)
        sub = self.retrieve_subscription(subscription_id)
        item = sub["items"]["data"][0]
        current_qty = item["quantity"]
        if seats >= current_qty:
            self.stripe.Subscription.modify(
                subscription_id,
                items=[{"id": item["id"], "quantity": seats}],
                proration_behavior="always_invoice",
            )
            return {"effect": "immediate", "seats": seats}
        # Decrease: schedule the reduction for the next billing cycle (current phase unchanged).
        schedule = self.stripe.SubscriptionSchedule.create(from_subscription=subscription_id)
        sched = self.stripe.SubscriptionSchedule.retrieve(schedule.id)
        phase = sched["phases"][0]
        price_id = self._seat_price_id()
        self.stripe.SubscriptionSchedule.modify(
            schedule.id,
            phases=[
                {"items": [{"price": price_id, "quantity": current_qty}],
                 "start_date": phase["start_date"], "end_date": phase["end_date"]},
                {"items": [{"price": price_id, "quantity": seats}]},
            ],
            proration_behavior="none",
        )
        return {"effect": "scheduled", "current_seats": current_qty, "pending_seats": seats,
                "effective_at": _ts_to_dt(phase["end_date"])}

    def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> dict:
        sub = self.stripe.Subscription.modify(subscription_id, cancel_at_period_end=cancel)
        return {"cancel_at_period_end": bool(sub["cancel_at_period_end"]),
                "current_period_end": _ts_to_dt(sub.get("current_period_end"))}

    async def portal_url(self, company_id: str) -> str | None:
        # Portal requires a Stripe customer id; resolved at the service layer by the CP subscription row.
        raise BillingAuthError("use create_portal_session(customer_id) for Stripe")

    def create_portal_session(self, customer_id: str, return_url: str | None = None) -> str:
        origin = (return_url or _cpc.APP_BASE_URL).rstrip("/")
        s = self.stripe.billing_portal.Session.create(
            customer=customer_id, return_url=f"{origin}/admin/subscription")
        return s.url

    def verify_and_parse_webhook(self, headers, body, payload):
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not sig:
            raise BillingAuthError("missing Stripe-Signature header")
        try:
            event = self.stripe.Webhook.construct_event(body, sig, self.webhook_secret)
        except Exception as e:  # SignatureVerificationError / ValueError
            raise BillingAuthError(f"invalid Stripe signature: {str(e)[:120]}")
        obj = event["data"]["object"]
        etype = event["type"]
        seats = period_end = cancel_flag = sub_id = cust_id = company_ref = None
        normalized = None
        if etype == "checkout.session.completed":
            company_ref = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("company_id")
            sub_id = obj.get("subscription")
            cust_id = obj.get("customer")
            normalized = ACTIVE
        elif etype in ("customer.subscription.created", "customer.subscription.updated"):
            norm = self.normalize_subscription(obj)
            normalized = norm["state"]
            seats = norm["seats"]
            period_end = norm["current_period_end"]
            cancel_flag = norm["cancel_at_period_end"]
            sub_id = norm["provider_subscription_id"]
            cust_id = norm["provider_customer_id"]
            company_ref = norm["company_reference"]
        elif etype == "customer.subscription.deleted":
            sub_id = obj.get("id")
            cust_id = obj.get("customer")
            normalized = CANCELLED
        elif etype == "invoice.payment_failed":
            sub_id = obj.get("subscription")
            cust_id = obj.get("customer")
            normalized = GRACE
        elif etype in ("invoice.paid", "invoice.payment_succeeded"):
            sub_id = obj.get("subscription")
            cust_id = obj.get("customer")
            period_end = _ts_to_dt(obj.get("period_end"))
            normalized = ACTIVE
        return ParsedWebhook(
            event_id=event["id"], event_type=etype,
            company_reference=company_ref or cust_id, timestamp_ms=int(event["created"]) * 1000,
            normalized_state=normalized, seats=seats, current_period_end=period_end,
            cancel_at_period_end=cancel_flag, provider_subscription_id=sub_id,
            provider_customer_id=cust_id, raw_object=obj if isinstance(obj, dict) else obj.to_dict(),
        )

    async def reconcile(self, company_id: str) -> dict:
        # Reconciliation resolves via the CP subscription row's provider_subscription_id (service layer).
        return {"state": None, "seats": None}


def get_provider() -> BillingProvider:
    mode = _cpc.BILLING_MODE
    if mode == "stripe":
        # Fail CLEARLY in production if Stripe is misconfigured — never silently fall back to mock.
        return StripeBillingProvider()
    if mode == "revenuecat":
        return RevenueCatStripeProvider()
    if mode == "stub":
        return StubBillingProvider()
    return MockBillingProvider()


def get_stripe_provider() -> "StripeBillingProvider":
    """Explicit Stripe provider (independent of BILLING_MODE) for the dedicated Stripe endpoints."""
    return StripeBillingProvider()

