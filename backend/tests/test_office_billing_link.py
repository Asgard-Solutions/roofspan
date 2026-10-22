"""Office "Manage billing" -> real Stripe (never the mock portal), incl. Windows installs without Stripe keys."""
import asyncio
from types import SimpleNamespace

import pytest

from control_plane import billing as cp_billing
from control_plane import config as cp_config
from control_plane import service as cp_service
from licensing import pairing_client
from routers import licensing as lic_router


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeStripe:
    def __init__(self):
        self.calls = []

    def create_portal_session(self, customer_id, return_url=None, *, return_to=None):
        self.calls.append(("portal", customer_id, return_to))
        return "https://billing.stripe.com/p/session/test_123"

    def create_checkout_session(self, company_id, seats, origin_url=None, *, success_url=None, cancel_url=None):
        self.calls.append(("checkout", company_id, seats, success_url, cancel_url))
        return "https://checkout.stripe.com/c/pay/cs_test_123"


def _cp(monkeypatch, sub, base="https://cp.roofspan.io", mode="stripe"):
    fake = FakeStripe()
    monkeypatch.setattr(cp_config, "BILLING_MODE", mode)
    monkeypatch.setattr(cp_config, "APP_BASE_URL", base)
    monkeypatch.setattr(cp_billing, "get_stripe_provider", lambda: fake)

    async def _get_sub(db, company_id):
        return sub

    async def _audit(db, **kw):
        fake.calls.append(("audit", kw["action"]))

    monkeypatch.setattr(cp_service, "_get_sub", _get_sub)
    monkeypatch.setattr(cp_service, "audit", _audit)
    return fake


CID = "a7d0738a-e1f7-4f98-a16c-00975895dbb4"


def test_subscribed_company_gets_stripe_customer_portal(monkeypatch):
    fake = _cp(monkeypatch, SimpleNamespace(provider_customer_id="cus_1", seats=7))
    r = asyncio.run(cp_service.installation_billing_session(None, company_id=CID))
    assert r["kind"] == "portal" and r["url"].startswith("https://billing.stripe.com/")
    assert fake.calls[0] == ("portal", "cus_1", "https://cp.roofspan.io/api/control-plane/billing/return?result=portal")


def test_never_subscribed_company_is_sent_to_stripe_checkout(monkeypatch):
    fake = _cp(monkeypatch, SimpleNamespace(provider_customer_id=None, seats=2))
    r = asyncio.run(cp_service.installation_billing_session(None, company_id=CID))
    assert r["kind"] == "checkout" and r["url"].startswith("https://checkout.stripe.com/")
    _, company, seats, success, cancel = fake.calls[0]
    assert company == CID and seats == cp_config.MIN_SEATS
    assert success.startswith("https://cp.roofspan.io/api/control-plane/billing/return?result=success")
    assert cancel == "https://cp.roofspan.io/api/control-plane/billing/return?result=cancel"


def test_control_plane_refuses_mock_mode_and_plain_http_redirects(monkeypatch):
    _cp(monkeypatch, SimpleNamespace(provider_customer_id="cus_1", seats=5), mode="mock")
    with pytest.raises(cp_service.CPError) as e:
        asyncio.run(cp_service.installation_billing_session(None, company_id=CID))
    assert e.value.status == 503
    _cp(monkeypatch, SimpleNamespace(provider_customer_id="cus_1", seats=5), base="http://cp.example.com")
    with pytest.raises(cp_service.CPError) as e:
        asyncio.run(cp_service.installation_billing_session(None, company_id=CID))
    assert "https" in e.value.detail


def test_unset_billing_mode_uses_stripe_not_mock(monkeypatch):
    monkeypatch.setattr(cp_config, "BILLING_MODE", "")
    monkeypatch.setattr(cp_billing.StripeBillingProvider, "__init__", lambda self: None)
    assert isinstance(cp_billing.get_provider(), cp_billing.StripeBillingProvider)
    monkeypatch.setattr(cp_config, "BILLING_MODE", "mock")
    assert isinstance(cp_billing.get_provider(), cp_billing.MockBillingProvider)


def _office(monkeypatch, cp_reply):
    sent = []

    async def ensure_registered(db):
        return "inst-1", object(), "https://cp.roofspan.io/api/control-plane"

    async def request_signed(method, base, path, installation_id, private_key, body=b""):
        sent.append((method, base, path, installation_id))
        return cp_reply

    monkeypatch.setattr(pairing_client, "ensure_registered", ensure_registered)
    monkeypatch.setattr(pairing_client, "_request_signed", request_signed)
    return sent


def test_windows_install_asks_hosted_control_plane_for_the_real_link(monkeypatch):
    """A Windows install has no Stripe keys and no BILLING_MODE: it must never build a mock-portal URL."""
    sent = _office(monkeypatch, FakeResponse(200, {"url": "https://billing.stripe.com/p/session/x", "kind": "portal"}))
    monkeypatch.setattr(cp_config, "BILLING_MODE", "stripe")
    monkeypatch.setattr(cp_config, "STRIPE_SECRET_KEY", "")

    async def get_installation(db):
        return None, CID

    monkeypatch.setattr(lic_router.service, "get_installation", get_installation)
    req = SimpleNamespace(headers={"origin": "http://localhost:3000"})
    for kind in ("portal", "checkout"):
        out = asyncio.run(lic_router._billing_link(req, None, kind))
        assert out.configured and out.url == "https://billing.stripe.com/p/session/x"
        assert "mock" not in out.url and "localhost" not in out.url
    assert sent[0] == ("POST", "https://cp.roofspan.io/api/control-plane", "/installation/billing/session", "inst-1")


def test_office_rejects_a_non_stripe_billing_link(monkeypatch):
    _office(monkeypatch, FakeResponse(200, {"url": "http://localhost:3000/mock-portal?app_user_id=x"}))
    with pytest.raises(pairing_client.ControlPlaneError, match="not a Stripe page"):
        asyncio.run(pairing_client.billing_session(None))


def test_control_plane_error_is_shown_not_replaced_by_a_mock(monkeypatch):
    _office(monkeypatch, FakeResponse(503, {"detail": "Billing is not enabled on the RoofSpan Control Plane"}))
    monkeypatch.setattr(cp_config, "BILLING_MODE", "stripe")
    monkeypatch.setattr(cp_config, "STRIPE_SECRET_KEY", "")

    async def get_installation(db):
        return None, CID

    monkeypatch.setattr(lic_router.service, "get_installation", get_installation)
    out = asyncio.run(lic_router._billing_link(SimpleNamespace(headers={}), None, "portal"))
    assert not out.configured and out.url is None and "not enabled" in out.message


def test_billing_return_page_never_echoes_input():
    from control_plane.installation_router import billing_return
    html = asyncio.run(billing_return("<script>alert(1)</script>")).body.decode()
    assert "<script>" not in html and "Billing updated" in html
    assert "Subscription started" in asyncio.run(billing_return("success")).body.decode()


def test_stripe_checkout_allows_promotion_codes(monkeypatch):
    captured = {}

    class _Sessions:
        @staticmethod
        def create(**kw):
            captured.update(kw)
            return SimpleNamespace(url="https://checkout.stripe.com/c/pay/cs_test_promo")

    p = cp_billing.StripeBillingProvider.__new__(cp_billing.StripeBillingProvider)
    p.stripe = SimpleNamespace(checkout=SimpleNamespace(Session=_Sessions))
    monkeypatch.setattr(p, "_seat_price_id", lambda: "price_seat", raising=False)
    monkeypatch.setattr(p, "_clamp", lambda s: s, raising=False)
    assert p.create_checkout_session(CID, 5, "https://app.roofspan.io").startswith("https://checkout.stripe.com/")
    assert captured["allow_promotion_codes"] is True and captured["mode"] == "subscription"
    assert "discounts" not in captured  # Stripe rejects discounts together with allow_promotion_codes
