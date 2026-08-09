"""Billing provider abstraction (interfaces + stub only for Phase C0).

RevenueCat + Stripe is the initial target (Phase C2) and Helcim may follow. Product, licensing,
seat enforcement, relay, installer and Mobile code depend ONLY on this normalized interface — never
on Stripe/RevenueCat-specific concepts. No real provider is implemented in Phase C0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol


@dataclass
class NormalizedSubscription:
    """Provider-agnostic subscription snapshot."""
    company_id: str
    state: str                       # ACTIVE | GRACE | SUSPENDED | CANCELLED
    seats: int
    renewal_at: Optional[datetime] = None
    provider: str = ""
    provider_customer_id: Optional[str] = None


@dataclass
class NormalizedSubscriptionEvent:
    """Provider-agnostic webhook event (used by the Billing Integration service in C2)."""
    event_id: str                    # for idempotency
    occurred_at: datetime
    subscription: NormalizedSubscription


@dataclass
class CheckoutSession:
    url: str
    provider: str


class BillingProvider(Protocol):
    """Interface every billing provider (Stripe/RevenueCat, later Helcim) must implement."""

    name: str

    def start_checkout(self, company_id: str, seats: int) -> CheckoutSession: ...

    def manage_billing_url(self, company_id: str) -> str: ...

    def normalize_webhook(self, headers: dict, raw_body: bytes) -> NormalizedSubscriptionEvent: ...


class BillingNotConfigured(Exception):
    """Raised when no real billing provider is configured (Phase C0/C1)."""


class StubBillingProvider:
    """Placeholder provider for Phase C0. Wiring exists; no processor is connected yet."""

    name = "stub"

    def start_checkout(self, company_id: str, seats: int) -> CheckoutSession:
        raise BillingNotConfigured("Billing provider not configured (RevenueCat/Stripe arrives in Phase C2).")

    def manage_billing_url(self, company_id: str) -> str:
        raise BillingNotConfigured("Billing provider not configured (RevenueCat/Stripe arrives in Phase C2).")

    def normalize_webhook(self, headers: dict, raw_body: bytes) -> NormalizedSubscriptionEvent:
        raise BillingNotConfigured("Billing provider not configured (RevenueCat/Stripe arrives in Phase C2).")


_provider: BillingProvider = StubBillingProvider()


def get_billing_provider() -> BillingProvider:
    return _provider
