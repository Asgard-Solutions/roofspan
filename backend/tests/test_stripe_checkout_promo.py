"""Focused unit test: hosted Stripe Checkout must expose the promotion-code field.

Verifies StripeBillingProvider.create_checkout_session() passes allow_promotion_codes=True (so a
customer can manually enter a valid promo code like OWNERTEST) while preserving mode, line items,
company metadata, automatic tax, billing-address/tax-id collection, and success/cancel URLs. No
network and no Stripe keys required (the stripe SDK is faked).

Run: cd /app/backend && python -m pytest tests/test_stripe_checkout_promo.py -o addopts='' -q
"""


class _FakePrice:
    @staticmethod
    def list(**_kw):
        class _R:
            data = [type("P", (), {"id": "price_123"})()]
        return _R()


class _FakeSession:
    created_kwargs: dict = {}

    @classmethod
    def create(cls, **kw):
        cls.created_kwargs = kw
        return type("S", (), {"url": "https://checkout.stripe.com/c/pay/cs_test_1"})()


class _FakeCheckout:
    Session = _FakeSession


class _FakeStripe:
    Price = _FakePrice
    checkout = _FakeCheckout


def _provider():
    from control_plane.billing import StripeBillingProvider
    prov = object.__new__(StripeBillingProvider)   # skip __init__ (no real Stripe keys needed)
    prov.stripe = _FakeStripe
    prov.lookup_key = "roofspan_seat_monthly"
    return prov


def test_create_checkout_session_allows_promotion_codes():
    prov = _provider()
    url = prov.create_checkout_session("co-1", 5)
    kw = _FakeSession.created_kwargs

    # The change under test.
    assert kw.get("allow_promotion_codes") is True

    # Everything else preserved exactly.
    assert kw["mode"] == "subscription"
    assert kw["line_items"] == [{"price": "price_123", "quantity": 5}]
    assert kw["client_reference_id"] == "co-1"
    assert kw["metadata"] == {"company_id": "co-1"}
    assert kw["subscription_data"] == {"metadata": {"company_id": "co-1"}}
    assert kw["automatic_tax"] == {"enabled": True}
    assert kw["billing_address_collection"] == "required"
    assert kw["tax_id_collection"] == {"enabled": True}
    assert "success_url" in kw and "cancel_url" in kw
    assert url == "https://checkout.stripe.com/c/pay/cs_test_1"

    # No coupon is auto-applied and no promo code is hard-coded (Stripe only exposes the input field).
    assert "discounts" not in kw and "coupon" not in kw


def test_no_promo_code_hardcoded_in_billing_source():
    import control_plane.billing as _b
    with open(_b.__file__) as f:
        src = f.read()
    assert "OWNERTEST" not in src
    assert "allow_promotion_codes=True" in src
