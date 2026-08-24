"""Server-side PDF generation (reportlab) for RoofSpan invoices AND quotes/estimates.
Renders the Company Profile (incl. logo) + customer + line items + totals."""
import base64
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage)


def _money(v) -> str:
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _fmt_date(v) -> str:
    if not v:
        return "—"
    try:
        return v.strftime("%b %d, %Y")
    except Exception:
        return str(v)[:10]


def _logo_flowable(logo_url: str, max_w=2.0 * inch, max_h=0.8 * inch):
    """Return a reportlab Image for the company logo (from a data: URL or http(s) URL), or None."""
    if not logo_url:
        return None
    try:
        if logo_url.startswith("data:"):
            data = base64.b64decode(logo_url.split(",", 1)[1])
        elif logo_url.startswith("http"):
            import requests
            r = requests.get(logo_url, timeout=10)
            r.raise_for_status()
            data = r.content
        else:
            return None
        iw, ih = ImageReader(io.BytesIO(data)).getSize()
        ratio = min(max_w / iw, max_h / ih)
        return RLImage(io.BytesIO(data), width=iw * ratio, height=ih * ratio)
    except Exception:
        return None


def _build_pdf(*, doc_type: str, doc: dict, company: dict, customer: dict | None, property_address: str | None) -> bytes:
    is_quote = doc_type in ("quote", "estimate")
    heading = "QUOTE" if is_quote else "INVOICE"
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch, title=f"{heading} {doc.get('number','')}")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Normal"], fontSize=9, leading=12)
    hb = ParagraphStyle("hb", parent=styles["Normal"], fontSize=9, leading=12, fontName="Helvetica-Bold")
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#64748b"))
    title = ParagraphStyle("title", parent=styles["Normal"], fontSize=22, leading=24, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#0f172a"), alignment=2)
    right = ParagraphStyle("right", parent=h, alignment=2)
    story = []

    company = company or {}
    comp_lines = "<br/>".join(filter(None, [
        f"<b>{company.get('name') or 'RoofSpan Roofing Co.'}</b>",
        company.get("address"), company.get("phone"), company.get("email"),
        company.get("website"), (f"License: {company.get('license_number')}" if company.get("license_number") else None),
    ]))
    logo = _logo_flowable(company.get("logo_url", ""))
    left_cell = [logo, Spacer(1, 6), Paragraph(comp_lines, h)] if logo else Paragraph(comp_lines, h)
    header = Table([[left_cell, Paragraph(heading, title)]], colWidths=[3.8 * inch, 3.2 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [header, Spacer(1, 0.25 * inch)]

    cust = customer or {}
    bill_label = "Prepared For" if is_quote else "Bill To"
    bill_to = "<br/>".join(filter(None, [
        f"<b>{bill_label}</b>", cust.get("name"), property_address, cust.get("billing_address"),
        cust.get("phone"), cust.get("email"),
    ])) or f"<b>{bill_label}</b><br/>—"
    date2_label = "Expires" if is_quote else "Due"
    date2_val = doc.get("expiration_date") if is_quote else doc.get("due_date")
    meta = [
        [Paragraph(f"{heading.title()} #", small), Paragraph(str(doc.get("number") or "—"), hb)],
        [Paragraph("Status", small), Paragraph(str(doc.get("status") or "—").title(), h)],
        [Paragraph("Issued", small), Paragraph(_fmt_date(doc.get("issue_date")), h)],
        [Paragraph(date2_label, small), Paragraph(_fmt_date(date2_val), h)],
    ]
    meta_tbl = Table(meta, colWidths=[0.9 * inch, 1.6 * inch])
    meta_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    top = Table([[Paragraph(bill_to, h), meta_tbl]], colWidths=[4.0 * inch, 3.0 * inch])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [top, Spacer(1, 0.3 * inch)]

    rows = [[Paragraph("Description", hb), Paragraph("Qty", hb), Paragraph("Unit", hb),
             Paragraph("Unit Price", hb), Paragraph("Amount", hb)]]
    for it in doc.get("items", []):
        up = it.get("selling_unit_price") if it.get("selling_unit_price") not in (None, "") else it.get("unit_price")
        amt = it.get("line_total") if it.get("line_total") is not None else it.get("selling_total")
        rows.append([Paragraph(str(it.get("description") or ""), h), Paragraph(str(it.get("quantity") or ""), h),
                     Paragraph(str(it.get("unit") or ""), h), Paragraph(_money(up), right), Paragraph(_money(amt), right)])
    items_tbl = Table(rows, colWidths=[3.4 * inch, 0.7 * inch, 0.7 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [items_tbl, Spacer(1, 0.15 * inch)]

    total_label = "Total" if is_quote else "Total Due"
    totals = [["Subtotal", _money(doc.get("subtotal"))],
              [f"Tax ({float(doc.get('tax_rate') or 0):.2f}%)", _money(doc.get("tax"))],
              [total_label, _money(doc.get("total"))]]
    tot_tbl = Table([[Paragraph(l, hb if i == 2 else h), Paragraph(v, ParagraphStyle("tb", parent=right,
                     fontName="Helvetica-Bold") if i == 2 else right)] for i, (l, v) in enumerate(totals)],
                    colWidths=[1.4 * inch, 1.3 * inch], hAlign="RIGHT")
    tot_tbl.setStyle(TableStyle([("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.HexColor("#0f172a")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [tot_tbl, Spacer(1, 0.3 * inch)]

    extra = doc.get("terms") if is_quote else doc.get("notes")
    extra_label = "Terms" if is_quote else "Notes"
    if extra:
        story += [Paragraph(f"<b>{extra_label}</b>", h), Paragraph(str(extra).replace("\n", "<br/>"), h), Spacer(1, 0.2 * inch)]
    footer = ("This quote is an estimate of work and pricing and is not a bill."
              if is_quote else
              "This invoice is a record of amounts owed. RoofSpan is not a payment processor — "
              "please contact us using the details above to arrange payment.")
    story += [Paragraph(footer, small)]

    pdf.build(story)
    return buf.getvalue()


def build_invoice_pdf(*, invoice: dict, company: dict, customer: dict | None, property_address: str | None) -> bytes:
    return _build_pdf(doc_type="invoice", doc=invoice, company=company, customer=customer, property_address=property_address)


def build_quote_pdf(*, quote: dict, company: dict, customer: dict | None, property_address: str | None) -> bytes:
    return _build_pdf(doc_type="quote", doc=quote, company=company, customer=customer, property_address=property_address)
