"""Customer Proposal — customer-safe rendering of a Quote from STORED snapshot values only.

Hard rule: this module NEVER reads supplier cost, material cost, markup/margin, Best Known Cost, or any
internal profitability field, and NEVER queries current supplier pricing. It renders only the customer-
facing selling values already snapshotted on the Quote / QuoteLineItem / QuotePackage.
"""
from __future__ import annotations
import io

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Quote, QuoteLineItem, QuotePackage, Customer, Property, AppConfig


def _money(v) -> str:
    return f"${float(v or 0):,.2f}"


def _dt(v):
    return v.strftime("%b %d, %Y") if v else None


async def _company(db: AsyncSession) -> dict:
    row = (await db.execute(select(AppConfig).where(AppConfig.key == "company_profile"))).scalar_one_or_none()
    v = row.value if row and isinstance(row.value, dict) else {}
    return {"name": v.get("name") or "RoofSpan Roofing Co.", "phone": v.get("phone", ""),
            "email": v.get("email", ""), "address": v.get("address", ""), "license_number": v.get("license_number", ""),
            "logo_url": v.get("logo_url", ""), "website": v.get("website", ""),
            "proposal_footer_text": v.get("proposal_footer_text", ""), "proposal_terms_text": v.get("proposal_terms_text", "")}


def _line(i: QuoteLineItem) -> dict:
    # selling values ONLY. unit_price is the customer selling price (internal cost is never on output).
    return {"description": i.description, "quantity": i.quantity, "unit": i.unit,
            "unit_price": i.unit_price, "line_total": i.line_total}


async def proposal_data(db: AsyncSession, quote: Quote) -> dict:
    company = await _company(db)
    cust = await db.get(Customer, quote.customer_id) if quote.customer_id else None
    prop = await db.get(Property, quote.property_id) if quote.property_id else None
    base_items = (await db.execute(select(QuoteLineItem).where(
        QuoteLineItem.quote_id == quote.id, QuoteLineItem.package_id.is_(None)).order_by(QuoteLineItem.sort))).scalars().all()
    packages = []
    if quote.multi_package:
        pkgs = (await db.execute(select(QuotePackage).where(QuotePackage.quote_id == quote.id).order_by(QuotePackage.sort, QuotePackage.tier))).scalars().all()
        for p in pkgs:
            pit = (await db.execute(select(QuoteLineItem).where(QuoteLineItem.package_id == p.id).order_by(QuoteLineItem.sort))).scalars().all()
            packages.append({"id": str(p.id), "name": p.name, "tier": p.tier, "subtotal": p.subtotal,
                             "tax": p.tax, "total": p.total, "notes": p.notes,
                             "accepted": str(p.id) == str(quote.accepted_package_id),
                             "lines": [_line(i) for i in pit]})
    return {
        "company": company,
        "quote": {
            "number": quote.number, "status": quote.status,
            "issue_date": _dt(quote.issue_date), "expiration_date": _dt(quote.expiration_date),
            "subtotal": quote.subtotal, "tax": quote.tax, "tax_rate": quote.tax_rate, "total": quote.total,
            "terms": quote.terms, "multi_package": quote.multi_package,
            "accepted_at": _dt(quote.accepted_at), "accepted_by": quote.accepted_by,
            "acceptance_name": quote.acceptance_name,
            "accepted_package_id": str(quote.accepted_package_id) if quote.accepted_package_id else None,
        },
        "customer": {"name": cust.name if cust else None} if cust else None,
        "property": {"address": prop.formatted_address if prop else None} if prop else None,
        "lines": [_line(i) for i in base_items],
        "packages": packages,
    }


def build_pdf(data: dict) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch, title=f"Proposal {data['quote']['number']}")
    styles = getSampleStyleSheet()
    ORANGE = colors.HexColor("#EA580C")
    SLATE = colors.HexColor("#0F172A")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=SLATE, fontSize=20, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"))
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#94A3B8"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, textColor=SLATE)
    story = []
    c = data["company"]

    # Header
    story.append(Paragraph(c["name"], h1))
    meta = " · ".join([x for x in [c.get("phone"), c.get("email"), c.get("website")] if x])
    if meta:
        story.append(Paragraph(meta, small))
    if c.get("address"):
        story.append(Paragraph(c["address"], small))
    if c.get("license_number"):
        story.append(Paragraph(f"License #{c['license_number']}", small))
    story.append(Spacer(1, 12))

    q = data["quote"]
    story.append(Paragraph(f"Proposal {q['number']}", ParagraphStyle("t", parent=styles["Heading2"], textColor=ORANGE)))
    info = []
    if q["issue_date"]:
        info.append(f"Issued: {q['issue_date']}")
    if q["expiration_date"]:
        info.append(f"Valid until: {q['expiration_date']}")
    if data.get("customer"):
        info.append(f"Prepared for: {data['customer']['name']}")
    if data.get("property") and data["property"]["address"]:
        info.append(f"Property: {data['property']['address']}")
    for line in info:
        story.append(Paragraph(line, body))
    story.append(Spacer(1, 12))

    def _items_table(lines, subtotal, tax, total):
        rows = [["Description", "Qty", "Unit", "Price", "Amount"]]
        for l in lines:
            rows.append([l["description"] or "", f"{l['quantity']:g}", l["unit"] or "",
                         _money(l["unit_price"]), _money(l["line_total"])])
        t = Table(rows, colWidths=[3.4 * inch, 0.7 * inch, 0.7 * inch, 1.0 * inch, 1.1 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SLATE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        out = [t, Spacer(1, 6)]
        tot = Table([["Subtotal", _money(subtotal)], ["Tax", _money(tax)], ["Total", _money(total)]],
                    colWidths=[6.0 * inch, 0.9 * inch])
        tot.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 10),
                                 ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"), ("TEXTCOLOR", (0, 2), (-1, 2), ORANGE),
                                 ("TOPPADDING", (0, 0), (-1, -1), 2)]))
        out.append(tot)
        return out

    if q["multi_package"] and data["packages"]:
        for p in data["packages"]:
            title = p["name"] + ("  ✓ Selected" if p["accepted"] else "")
            story.append(Paragraph(title, ParagraphStyle("pk", parent=styles["Heading3"],
                                   textColor=ORANGE if p["accepted"] else SLATE)))
            story.extend(_items_table(p["lines"], p["subtotal"], p["tax"], p["total"]))
            story.append(Spacer(1, 14))
    else:
        story.extend(_items_table(data["lines"], q["subtotal"], q["tax"], q["total"]))
        story.append(Spacer(1, 10))

    if q.get("terms") or c.get("proposal_terms_text"):
        story.append(Spacer(1, 8))
        story.append(Paragraph("Terms", ParagraphStyle("th", parent=styles["Heading4"], textColor=SLATE)))
        story.append(Paragraph((q.get("terms") or c.get("proposal_terms_text") or "").replace("\n", "<br/>"), small))

    if q.get("accepted_at"):
        story.append(Spacer(1, 10))
        acc = f"Accepted by {q.get('acceptance_name') or q.get('accepted_by') or 'customer'} on {q['accepted_at']}"
        story.append(Paragraph(acc, ParagraphStyle("acc", parent=body, textColor=colors.HexColor("#16A34A"))))

    if c.get("proposal_footer_text"):
        story.append(Spacer(1, 16))
        story.append(Paragraph(c["proposal_footer_text"], label))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
