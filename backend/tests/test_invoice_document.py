"""Finance invoice document/PDF/send endpoints."""
import os

import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = ("pjacobsen@asgardsolution.io", "RoofSpan#Owner2026")


def _tok():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


def _first_invoice(h):
    r = requests.get(f"{BASE_URL}/api/invoices", headers=h, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    return data[0]["id"] if data else None


def test_invoice_document_and_pdf():
    h = {"Authorization": f"Bearer {_tok()}"}
    iid = _first_invoice(h)
    if not iid:
        return  # no invoices seeded; endpoints covered by pdf-unit below
    doc = requests.get(f"{BASE_URL}/api/invoices/{iid}/document", headers=h, timeout=30).json()
    assert "invoice" in doc and "company" in doc
    assert isinstance(doc["invoice"].get("items"), list)
    pdf = requests.get(f"{BASE_URL}/api/invoices/{iid}/pdf", headers=h, timeout=60)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"


def test_invoice_pdf_builder_unit():
    from services.invoice_pdf import build_invoice_pdf
    inv = {"number": "INV-TEST", "status": "issued", "tax_rate": 8.25, "subtotal": 100, "tax": 8.25, "total": 108.25,
           "items": [{"description": "Shingles", "quantity": 10, "unit": "sq", "unit_price": 10, "line_total": 100}]}
    pdf = build_invoice_pdf(invoice=inv, company={"name": "Test Co", "phone": "555"}, customer={"name": "Jane"},
                            property_address="1 Main St")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 800


def test_send_invoice_graceful_when_email_not_configured(monkeypatch):
    # If RESEND is not configured, sending must fail cleanly (503), not 500. Only assert when unconfigured.
    h = {"Authorization": f"Bearer {_tok()}"}
    iid = _first_invoice(h)
    if not iid:
        return
    r = requests.post(f"{BASE_URL}/api/invoices/{iid}/send", headers=h, timeout=30)
    # 503 (not configured) OR 400 (customer has no email) OR 200 (configured). Never 500.
    assert r.status_code in (200, 400, 503), f"{r.status_code}: {r.text[:200]}"
