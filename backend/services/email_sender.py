"""Application-wide email sending — SINGLE choke point for ALL RoofSpan emails.

Right now email delivery is intentionally STUBBED: every send is recorded (logged) and returns a
stub id, but no message actually leaves the machine. When the email transport is decided later
(SMTP / Resend / SES / etc.), implement it in `_send_via_provider` behind the EMAIL_PROVIDER switch
and every caller (invoices today, plus future features) starts sending for free — no caller changes.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logger = logging.getLogger("roofspan.email")


class EmailNotConfigured(RuntimeError):
    pass


def email_provider() -> str:
    """'stub' (default, no delivery) until a real transport is chosen for the whole app."""
    return (os.environ.get("EMAIL_PROVIDER") or "stub").strip().lower()


async def send_email(*, to: str, subject: str, html: str, attachments: list[dict] | None = None) -> dict:
    """Send one email through the app-wide transport. Returns {email_id, stubbed}.
    attachments: list of {filename, content(bytes)}.
    """
    provider = email_provider()
    if provider == "stub":
        logger.info("EMAIL STUB → to=%s subject=%r attachments=%s (no message sent; delivery not configured)",
                    to, subject, [a.get("filename") for a in (attachments or [])])
        return {"email_id": f"stub-{abs(hash((to, subject))) % 10**10}", "stubbed": True}
    return await _send_via_provider(provider, to=to, subject=subject, html=html, attachments=attachments)


async def _send_via_provider(provider: str, *, to: str, subject: str, html: str,
                             attachments: list[dict] | None) -> dict:
    """Future real transport(s) plug in here. Kept unimplemented on purpose per product decision to
    centralise all email delivery later."""
    raise EmailNotConfigured(
        f"Email provider '{provider}' is not implemented yet. Email delivery for RoofSpan will be "
        "configured centrally later; for now use Print or Download PDF."
    )


def _money(v) -> str:
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _invoice_html(invoice: dict, company: dict) -> str:
    comp = (company or {}).get("name") or "RoofSpan Roofing Co."
    contact = " · ".join(filter(None, [(company or {}).get("phone"), (company or {}).get("email")]))
    return (
        f'<div style="font-family:Arial,Helvetica,sans-serif;color:#0f172a;font-size:14px;line-height:1.5">'
        f'<p>Hello,</p>'
        f'<p>Please find attached invoice <b>{invoice.get("number","")}</b> from <b>{comp}</b> '
        f'for a total of <b>{_money(invoice.get("total"))}</b>.</p>'
        f'<p>RoofSpan is not a payment processor — to arrange payment or ask any questions, '
        f'please contact us{(" at " + contact) if contact else ""}.</p>'
        f'<p>Thank you,<br/>{comp}</p></div>'
    )


async def send_invoice_email(*, to_email: str, invoice: dict, company: dict, pdf_bytes: bytes) -> dict:
    """Send an invoice (PDF attached) through the app-wide email transport."""
    return await send_email(
        to=to_email,
        subject=f"Invoice {invoice.get('number','')} from {(company or {}).get('name') or 'RoofSpan'}",
        html=_invoice_html(invoice, company),
        attachments=[{"filename": f"Invoice-{invoice.get('number','')}.pdf", "content": pdf_bytes}],
    )
