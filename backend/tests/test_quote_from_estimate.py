"""Regression test for: Quote generated from Estimate must carry qty/price and non-zero total."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://roofspan-cloud-test.preview.emergentagent.com").rstrip("/")
OWNER_EMAIL = "pjacobsen@asgardsolution.io"
OWNER_PASSWORD = "RoofSpan#Owner2026"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def lead_and_customer(headers):
    # Use existing seeded lead from review request
    lead_id = "487c6557-a3ff-416e-b444-68b54e4f5096"
    r = requests.get(f"{BASE_URL}/api/leads/{lead_id}", headers=headers, allow_redirects=True)
    assert r.status_code == 200, r.text
    d = r.json()
    return {"customer_id": d["customer_id"], "lead_id": lead_id, "property_id": d.get("property_id")}


def _create_estimate(headers, lead_id, customer_id, items, tax_rate=8.25):
    payload = {
        "lead_id": lead_id,
        "customer_id": customer_id,
        "tax_rate": tax_rate,
        "items": items,
    }
    r = requests.post(f"{BASE_URL}/api/estimates", json=payload, headers=headers, allow_redirects=True)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_quote_from_estimate_carries_qty_and_price(headers, lead_and_customer):
    # Estimate: qty=3, sell=100 => line_total=300, subtotal=300, total = 300*1.0825 = 324.75
    items = [{
        "description": "Test Shingle Bundle",
        "quantity": 3,
        "measured_quantity": 3,
        "unit": "bundle",
        "selling_unit_price": 100.0,
        "unit_price": 100.0,
        "material_cost": 60.0,
    }]
    est = _create_estimate(headers, lead_and_customer["lead_id"], lead_and_customer["customer_id"], items, tax_rate=8.25)
    est_id = est["id"]
    print(f"Estimate {est['number']} subtotal={est.get('subtotal')} total={est.get('total')} items={est.get('items')}")
    assert est.get("subtotal", 0) > 0, f"Estimate subtotal should be non-zero: {est}"

    # Generate quote from estimate
    r = requests.post(f"{BASE_URL}/api/quotes", json={"estimate_id": est_id}, headers=headers, allow_redirects=True)
    assert r.status_code in (200, 201), r.text
    q = r.json()
    print(f"Quote {q['number']} subtotal={q['subtotal']} tax={q['tax']} total={q['total']} items={q['items']}")

    assert q["subtotal"] > 0, f"Quote subtotal is zero! {q}"
    assert q["total"] > 0, f"Quote total is zero! {q}"
    assert len(q["items"]) == 1
    line = q["items"][0]
    assert line["quantity"] == 3, line
    assert float(line["selling_unit_price"]) == 100.0, line
    assert float(line["line_total"]) == 300.0, line
    # Estimate total must match quote total
    assert round(q["subtotal"], 2) == 300.00
    assert round(q["total"], 2) == round(300.0 * 1.0825, 2)


def test_quote_from_estimate_with_measured_quantity_only(headers, lead_and_customer):
    # Simulate case where quantity may be absent/zero, only measured_quantity set
    items = [{
        "description": "Measured Only Line",
        "measured_quantity": 5,
        "quantity": 0,  # deliberately zero to test fallback
        "unit": "sq",
        "unit_price": 50.0,  # only unit_price, no selling_unit_price
    }]
    est = _create_estimate(headers, lead_and_customer["lead_id"], lead_and_customer["customer_id"], items, tax_rate=0)
    est_id = est["id"]
    print(f"Estimate2 {est['number']} subtotal={est.get('subtotal')} items={est.get('items')}")

    r = requests.post(f"{BASE_URL}/api/quotes", json={"estimate_id": est_id}, headers=headers, allow_redirects=True)
    assert r.status_code in (200, 201), r.text
    q = r.json()
    print(f"Quote2 {q['number']} subtotal={q['subtotal']} total={q['total']} items={q['items']}")
    # Should not be zero even though quantity was 0 (fallback to measured_quantity)
    assert q["subtotal"] > 0, f"Quote subtotal zero when only measured_quantity provided: {q}"
    assert len(q["items"]) == 1
    assert q["items"][0]["quantity"] == 5
    assert float(q["items"][0]["selling_unit_price"]) == 50.0
    assert float(q["items"][0]["line_total"]) == 250.0


def test_quote_from_estimate_multi_line(headers, lead_and_customer):
    items = [
        {"description": "Line A", "quantity": 2, "unit": "ea", "selling_unit_price": 25.0},
        {"description": "Line B", "quantity": 4, "unit": "ea", "selling_unit_price": 10.0},
        {"description": "Line C", "quantity": 1, "unit": "ea", "selling_unit_price": 100.0},
    ]
    est = _create_estimate(headers, lead_and_customer["lead_id"], lead_and_customer["customer_id"], items, tax_rate=10.0)
    est_id = est["id"]

    r = requests.post(f"{BASE_URL}/api/quotes", json={"estimate_id": est_id}, headers=headers, allow_redirects=True)
    assert r.status_code in (200, 201), r.text
    q = r.json()
    print(f"MultiQuote {q['number']} subtotal={q['subtotal']} total={q['total']}")
    # 50 + 40 + 100 = 190
    assert round(q["subtotal"], 2) == 190.00
    assert round(q["total"], 2) == 209.00  # 190 * 1.10
    assert len(q["items"]) == 3


def test_accepted_quote_cannot_be_deleted_or_edited(headers, lead_and_customer):
    items = [{"description": "Accept test", "quantity": 1, "unit": "ea", "selling_unit_price": 500.0}]
    est = _create_estimate(headers, lead_and_customer["lead_id"], lead_and_customer["customer_id"], items, tax_rate=0)
    r = requests.post(f"{BASE_URL}/api/quotes", json={"estimate_id": est["id"]}, headers=headers, allow_redirects=True)
    assert r.status_code in (200, 201)
    q = r.json()
    qid = q["id"]
    # Accept
    r = requests.post(f"{BASE_URL}/api/quotes/{qid}/accept",
                     json={"acceptance_name": "Test User"},
                     headers=headers, allow_redirects=True)
    print(f"Accept response: {r.status_code} {r.text[:200]}")
    if r.status_code not in (200, 201):
        pytest.skip(f"Could not accept quote: {r.status_code} {r.text}")

    # Try to delete - expect 409/400
    r = requests.delete(f"{BASE_URL}/api/quotes/{qid}", headers=headers, allow_redirects=True)
    print(f"Delete accepted quote: {r.status_code} {r.text[:200]}")
    assert r.status_code in (400, 409), f"Accepted quote should not be deletable, got {r.status_code}"

    # Try to update - expect 400/409
    r = requests.put(f"{BASE_URL}/api/quotes/{qid}",
                    json={"terms": "changed"},
                    headers=headers, allow_redirects=True)
    print(f"Edit accepted quote: {r.status_code} {r.text[:200]}")
    assert r.status_code in (400, 409), f"Accepted quote should not be editable, got {r.status_code}"
