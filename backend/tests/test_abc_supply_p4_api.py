"""ABC Supply — Phase 4 end-to-end API tests hitting the deployed backend via REACT_APP_BACKEND_URL.

Covers: register/reconcile, webhook auth (401 cases), ORDER_UPDATE, idempotency, offline→reconnect,
NO auto-receiving, ORDER_INVOICED (Authorization + apiKey transport), unmatched routing, RBAC,
public ingress does not require JWT.
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")

OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASS = "RoofSpan#Owner2026"
SALES_EMAIL = "sales1_38f545f9@example.com"
SALES_PASS = "Sales1#2026"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def owner_token():
    return _login(OWNER_EMAIL, OWNER_PASS)


@pytest.fixture(scope="module")
def sales_token():
    try:
        return _login(SALES_EMAIL, SALES_PASS)
    except AssertionError:
        pytest.skip("sales user not available")


@pytest.fixture(scope="module")
def owner_headers(owner_token):
    return {"Authorization": f"Bearer {owner_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def registration(owner_headers):
    """Register (or reconcile) the ABC webhook. Return webhook_id + secret."""
    r = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/register", headers=owner_headers, timeout=30)
    assert r.status_code == 200, f"register failed {r.status_code} {r.text}"
    body = r.json()
    assert body.get("status") == "REGISTERED"
    assert body.get("webhook_id"), body
    assert body.get("has_secret") is True
    wid = body["webhook_id"]
    return {"webhook_id": wid, "secret": f"MOCK-WEBHOOK-SECRET-{wid}"}


@pytest.fixture(scope="module")
def po_ctx(owner_headers):
    """Create an ABC PO + submit it so an AbcOrderRoute exists. Yield the PO details."""
    body = {
        "supplier_name": "ABC Supply",
        "integration_provider": "abc_supply",
        "abc_ship_to_number": "1163698",
        "abc_branch_number": "18",
        "items": [{
            "description": "Owens Corning WeatherWatch (Mock)",
            "quantity": 5,
            "unit": "each",
            "unit_cost": 135.36,
            "integration_provider": "abc_supply",
            "abc_item_number": "MOCK-SHINGLE-ARCH-WW",
            "abc_branch_number": "18",
            "abc_ship_to_number": "1163698",
            "abc_uom": "EA",
            "abc_variation": None,
            "abc_price": 135.36,
            "abc_price_status": "priced",
            "abc_product_description": "Owens Corning WeatherWatch (Mock)",
            "pricing_source": "abc",
        }],
    }
    r = requests.post(f"{BASE_URL}/api/purchase-orders", headers=owner_headers, json=body, timeout=30)
    assert r.status_code == 201, f"create PO failed {r.status_code} {r.text}"
    po = r.json()
    po_id = po["id"]
    po_num = po["number"]

    # abc-submit-review then abc-submit
    r2 = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit-review",
                       headers=owner_headers, json={"apply_price_changes": True}, timeout=30)
    assert r2.status_code == 200, f"review failed: {r2.status_code} {r2.text}"

    sub_key = f"p4test-{uuid.uuid4().hex[:12]}"
    r3 = requests.post(f"{BASE_URL}/api/purchase-orders/{po_id}/abc-submit",
                       headers=owner_headers,
                       json={"submission_key": sub_key, "accept_price_changes": True, "delivery_service": "OTG",
                             "delivery": {"name": po_num, "requested_date": "2026-06-15"}},
                       timeout=60)
    assert r3.status_code == 200, f"submit failed: {r3.status_code} {r3.text}"
    sub_body = r3.json()
    assert sub_body.get("status") in ("confirmed", "already_submitted"), sub_body
    conf = sub_body.get("confirmation_number")
    return {"po_id": po_id, "po_number": po_num, "confirmation_number": conf}


# ------------------------- Tests -------------------------

class TestRegistration:
    def test_register_returns_reg_state(self, owner_headers, registration):
        assert registration["webhook_id"]

    def test_status_shows_registration(self, owner_headers, registration):
        r = requests.get(f"{BASE_URL}/api/integrations/abc/notifications/status", headers=owner_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "REGISTERED"
        assert body["webhook_id"] == registration["webhook_id"]
        assert set(body["events"]) == {"ORDER_UPDATE", "ORDER_INVOICED"}
        assert body["online"] is True
        assert body["has_secret"] is True
        # Secret must NEVER be exposed
        assert "secret" not in body
        assert "secret_ciphertext" not in body

    def test_register_is_idempotent_reconcile(self, owner_headers, registration):
        r = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/register", headers=owner_headers, timeout=30)
        assert r.status_code == 200
        assert r.json()["webhook_id"] == registration["webhook_id"]
        # Only one webhook still
        r2 = requests.get(f"{BASE_URL}/api/integrations/abc/notifications/status", headers=owner_headers, timeout=30)
        assert r2.json()["webhook_id"] == registration["webhook_id"]


class TestWebhookAuth:
    def test_missing_auth_401(self):
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          json={"eventType": "ORDER_UPDATE", "eventId": "auth-none", "data": {"purchaseOrderNumber": "X"}},
                          timeout=30)
        assert r.status_code == 401, r.text

    def test_wrong_auth_401(self):
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": "Bearer WRONG"},
                          json={"eventType": "ORDER_UPDATE", "eventId": "auth-wrong", "data": {"purchaseOrderNumber": "X"}},
                          timeout=30)
        assert r.status_code == 401, r.text

    def test_public_ingress_does_not_require_jwt(self, registration, po_ctx):
        # Should accept with just secret (no JWT). This is the crux of the "public" endpoint.
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": registration["secret"]},
                          json={"eventType": "ORDER_UPDATE", "eventId": f"noJWT-{uuid.uuid4().hex[:8]}",
                                "data": {"purchaseOrderNumber": po_ctx["po_number"], "status": "Acknowledged"}},
                          timeout=30)
        assert r.status_code == 200, r.text


class TestOrderUpdateFlow:
    def test_order_update_applies_to_po(self, owner_headers, registration, po_ctx):
        eid = f"ev-upd-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": registration["secret"]},
                          json={"eventType": "ORDER_UPDATE", "eventId": eid,
                                "data": {"purchaseOrderNumber": po_ctx["po_number"], "status": "Scheduled"}},
                          timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("routing") == "matched", body

        # Verify PO was updated
        rp = requests.get(f"{BASE_URL}/api/purchase-orders/{po_ctx['po_id']}", headers=owner_headers, timeout=30)
        assert rp.status_code == 200
        po = rp.json()
        assert po.get("abc_order_status") == "Scheduled", po
        assert po.get("abc_normalized_status") == "scheduled", po

    def test_duplicate_event_is_idempotent(self, owner_headers, registration, po_ctx):
        eid = f"ev-dup-{uuid.uuid4().hex[:8]}"
        payload = {"eventType": "ORDER_UPDATE", "eventId": eid,
                   "data": {"purchaseOrderNumber": po_ctx["po_number"], "status": "Picking"}}
        r1 = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                           headers={"Authorization": registration["secret"]}, json=payload, timeout=30)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                           headers={"Authorization": registration["secret"]}, json=payload, timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("duplicate") is True, r2.json()

        # PO status should be "Picking" (from first event) - not applied twice
        rp = requests.get(f"{BASE_URL}/api/purchase-orders/{po_ctx['po_id']}", headers=owner_headers, timeout=30)
        assert rp.json().get("abc_order_status") == "Picking"


class TestOfflineReconnect:
    def test_offline_queue_then_reconnect_delivers_once(self, owner_headers, registration, po_ctx):
        # Go offline
        r0 = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/simulate-offline?online=false",
                           headers=owner_headers, timeout=30)
        assert r0.status_code == 200 and r0.json().get("online") is False

        # Post while offline
        eid = f"ev-off-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": registration["secret"]},
                          json={"eventType": "ORDER_UPDATE", "eventId": eid,
                                "data": {"purchaseOrderNumber": po_ctx["po_number"], "status": "Shipped"}},
                          timeout=30)
        assert r.status_code == 200

        # PO status should NOT be "Shipped" yet (still whatever was before, e.g. Picking)
        rp = requests.get(f"{BASE_URL}/api/purchase-orders/{po_ctx['po_id']}", headers=owner_headers, timeout=30)
        pre_status = rp.json().get("abc_order_status")
        assert pre_status != "Shipped", f"should be queued, got {pre_status}"

        # Reconnect
        rc = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/reconnect", headers=owner_headers, timeout=30)
        assert rc.status_code == 200, rc.text
        delivered = rc.json().get("delivered", 0)
        assert delivered >= 1, rc.json()

        # PO should now be Shipped
        rp2 = requests.get(f"{BASE_URL}/api/purchase-orders/{po_ctx['po_id']}", headers=owner_headers, timeout=30)
        assert rp2.json().get("abc_order_status") == "Shipped"

        # Re-run reconnect: should not re-deliver
        rc2 = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/reconnect", headers=owner_headers, timeout=30)
        assert rc2.status_code == 200
        assert rc2.json().get("delivered", 0) == 0, rc2.json()


class TestNoAutoReceive:
    def test_shipped_does_not_receive_inventory(self, owner_headers, po_ctx):
        rp = requests.get(f"{BASE_URL}/api/purchase-orders/{po_ctx['po_id']}", headers=owner_headers, timeout=30)
        po = rp.json()
        # After the Shipped webhook event, PO status must NOT be received/partially_received
        assert po["status"] not in ("received", "partially_received"), po["status"]
        # Received quantity on line must still be 0
        for line in po.get("items", []) or po.get("lines", []) or []:
            assert (line.get("received_quantity") or 0) == 0, line


class TestOrderInvoiced:
    def test_invoiced_via_authorization_header(self, owner_headers, registration, po_ctx):
        eid = f"inv-auth-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": registration["secret"]},
                          json={"eventType": "ORDER_INVOICED", "eventId": eid,
                                "data": {"purchaseOrderNumber": po_ctx["po_number"],
                                         "invoiceNumber": "MOCK-INVOICE-555",
                                         "invoiceDate": "2026-06-18"}},
                          timeout=30)
        assert r.status_code == 200, r.text
        # Fetch events
        rev = requests.get(f"{BASE_URL}/api/integrations/abc/notifications/events/{po_ctx['po_id']}",
                           headers=owner_headers, timeout=30)
        assert rev.status_code == 200, rev.text
        body = rev.json()
        invs = body.get("invoices", [])
        assert any(i.get("invoice_number") == "MOCK-INVOICE-555" for i in invs), body

    def test_invoiced_via_apikey_field(self, owner_headers, registration, po_ctx):
        eid = f"inv-key-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          json={"eventType": "ORDER_INVOICED", "eventId": eid,
                                "data": {"purchaseOrderNumber": po_ctx["po_number"],
                                         "invoiceNumber": "MOCK-INVOICE-556",
                                         "invoiceDate": "2026-06-19",
                                         "apiKey": registration["secret"]}},
                          timeout=30)
        assert r.status_code == 200, r.text
        rev = requests.get(f"{BASE_URL}/api/integrations/abc/notifications/events/{po_ctx['po_id']}",
                           headers=owner_headers, timeout=30)
        assert any(i.get("invoice_number") == "MOCK-INVOICE-556" for i in rev.json().get("invoices", []))


class TestUnmatched:
    def test_unknown_po_returns_unmatched(self, registration):
        eid = f"unm-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{BASE_URL}/api/webhooks/abc/orders",
                          headers={"Authorization": registration["secret"]},
                          json={"eventType": "ORDER_UPDATE", "eventId": eid,
                                "data": {"purchaseOrderNumber": "PO-NOPE-9999", "status": "Scheduled"}},
                          timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("routing") == "unmatched"


class TestRBAC:
    def test_sales_cannot_register(self, sales_token):
        h = {"Authorization": f"Bearer {sales_token}"}
        r = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/register", headers=h, timeout=30)
        assert r.status_code == 403, r.text

    def test_sales_cannot_status(self, sales_token):
        h = {"Authorization": f"Bearer {sales_token}"}
        r = requests.get(f"{BASE_URL}/api/integrations/abc/notifications/status", headers=h, timeout=30)
        assert r.status_code == 403, r.text

    def test_sales_cannot_reconnect(self, sales_token):
        h = {"Authorization": f"Bearer {sales_token}"}
        r = requests.post(f"{BASE_URL}/api/integrations/abc/notifications/reconnect", headers=h, timeout=30)
        assert r.status_code == 403, r.text
