"""Server-side invoice PDF generation (reportlab). Renders company profile + customer + line items."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)


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


def build_invoice_pdf(*, invoice: dict, company: dict, customer: dict | None, property_address: str | None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch, title=f"Invoice {invoice.get('number','')}")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Normal"], fontSize=9, leading=12)
    hb = ParagraphStyle("hb", parent=styles["Normal"], fontSize=9, leading=12, fontName="Helvetica-Bold")
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#64748b"))
    title = ParagraphStyle("title", parent=styles["Normal"], fontSize=22, leading=24, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#0f172a"))
    right = ParagraphStyle("right", parent=h, alignment=2)
    story = []

    company = company or {}
    comp_lines = "<br/>".join(filter(None, [
        f"<b>{company.get('name') or 'RoofSpan Roofing Co.'}</b>",
        company.get("address"), company.get("phone"), company.get("email"),
        company.get("website"), (f"License: {company.get('license_number')}" if company.get("license_number") else None),
    ]))
    header = Table([[Paragraph(comp_lines, h), Paragraph("INVOICE", title)]],
                   colWidths=[3.6 * inch, 3.4 * inch])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    story += [header, Spacer(1, 0.25 * inch)]

    cust = customer or {}
    bill_to = "<br/>".join(filter(None, [
        "<b>Bill To</b>", cust.get("name"), property_address, cust.get("billing_address"),
        cust.get("phone"), cust.get("email"),
    ])) or "<b>Bill To</b><br/>—"
    meta = [
        [Paragraph("Invoice #", small), Paragraph(str(invoice.get("number") or "—"), hb)],
        [Paragraph("Status", small), Paragraph(str(invoice.get("status") or "—").title(), h)],
        [Paragraph("Issued", small), Paragraph(_fmt_date(invoice.get("issue_date")), h)],
        [Paragraph("Due", small), Paragraph(_fmt_date(invoice.get("due_date")), h)],
    ]
    meta_tbl = Table(meta, colWidths=[0.9 * inch, 1.6 * inch])
    meta_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    top = Table([[Paragraph(bill_to, h), meta_tbl]], colWidths=[4.0 * inch, 3.0 * inch])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [top, Spacer(1, 0.3 * inch)]

    rows = [[Paragraph("Description", hb), Paragraph("Qty", hb), Paragraph("Unit", hb),
             Paragraph("Unit Price", hb), Paragraph("Amount", hb)]]
    for it in invoice.get("items", []):
        rows.append([Paragraph(str(it.get("description") or ""), h), Paragraph(str(it.get("quantity") or ""), h),
                     Paragraph(str(it.get("unit") or ""), h), Paragraph(_money(it.get("unit_price")), right),
                     Paragraph(_money(it.get("line_total")), right)])
    items_tbl = Table(rows, colWidths=[3.4 * inch, 0.7 * inch, 0.7 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#0f172a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [items_tbl, Spacer(1, 0.15 * inch)]

    totals = [["Subtotal", _money(invoice.get("subtotal"))],
              [f"Tax ({float(invoice.get('tax_rate') or 0):.2f}%)", _money(invoice.get("tax"))],
              ["Total Due", _money(invoice.get("total"))]]
    tot_tbl = Table([[Paragraph(l, hb if i == 2 else h), Paragraph(v, right if i != 2 else
                     ParagraphStyle("tb", parent=right, fontName="Helvetica-Bold"))] for i, (l, v) in enumerate(totals)],
                    colWidths=[1.4 * inch, 1.3 * inch], hAlign="RIGHT")
    tot_tbl.setStyle(TableStyle([("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.HexColor("#0f172a")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [tot_tbl, Spacer(1, 0.3 * inch)]

    if invoice.get("notes"):
        story += [Paragraph("<b>Notes</b>", h), Paragraph(str(invoice["notes"]).replace("\n", "<br/>"), h), Spacer(1, 0.2 * inch)]
    story += [Paragraph(
        "This invoice is a record of amounts owed. RoofSpan is not a payment processor — "
        "please contact us using the details above to arrange payment.", small)]

    doc.build(story)
    return buf.getvalue()
