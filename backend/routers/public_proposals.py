"""Customer-facing PUBLIC proposal endpoints (no login) reached via a signed, quote-scoped share
link. These never expose internal cost — they reuse the same customer-safe `proposal_data` used by
the Office proposal preview. Accepting from the link runs the identical acceptance logic (creating a
Job) as the Office 'Accept' action."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Quote
from core import verify_proposal_share_token
from services import proposal as _proposal

public_router = APIRouter(prefix="/api/public/proposals", tags=["public-proposals"])


def _as_utc(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _expired(q: Quote) -> bool:
    exp = _as_utc(q.expiration_date)
    return bool(exp and datetime.now(timezone.utc) > exp)


async def _load(db: AsyncSession, token: str) -> Quote:
    quote_id = verify_proposal_share_token(token)
    q = await db.get(Quote, quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="This proposal link is invalid or has expired.")
    return q


class PublicAcceptIn(BaseModel):
    acceptance_name: str
    agreed: bool = False
    package_id: str | None = None


@public_router.get("/{token}")
async def public_proposal(token: str, db: AsyncSession = Depends(get_db)):
    q = await _load(db, token)
    data = await _proposal.proposal_data(db, q)
    from routers.measurements import _latest_site_plan_rev
    rev = await _latest_site_plan_rev(db, q.lead_id)
    data["site_plan_available"] = bool(rev and (rev.site_plan or {}).get("pdf_key"))
    data["share"] = {
        "status": q.status,
        "expired": _expired(q),
        "can_accept": q.status in ("draft", "sent") and not _expired(q),
        "multi_package": bool(q.multi_package),
    }
    return data


@public_router.post("/{token}/accept")
async def public_accept(token: str, payload: PublicAcceptIn, request: Request, db: AsyncSession = Depends(get_db)):
    q = await _load(db, token)
    if q.status == "accepted":
        return {"ok": True, "status": "accepted", "message": "This proposal has already been accepted."}
    if q.status not in ("draft", "sent"):
        raise HTTPException(status_code=409, detail="This proposal is no longer available to accept.")
    if _expired(q):
        raise HTTPException(status_code=400, detail="This proposal has expired. Please contact us for an updated proposal.")
    name = (payload.acceptance_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please type your full name to accept.")
    if not payload.agreed:
        raise HTTPException(status_code=400, detail="Please agree to the terms to accept this proposal.")
    from routers.quotes import perform_quote_acceptance
    q, job = await perform_quote_acceptance(db, q, acceptance_name=name, package_id=payload.package_id,
                                            accepted_by=f"customer:{name}", notes="Accepted online via share link",
                                            request=request, user=None)
    return {"ok": True, "status": "accepted", "message": "Thank you — your proposal has been accepted."}


@public_router.get("/{token}/proposal.pdf")
async def public_proposal_pdf(token: str, db: AsyncSession = Depends(get_db)):
    q = await _load(db, token)
    data = await _proposal.proposal_data(db, q)
    from routers.quotes import _lead_site_plan_png
    data["site_plan_png"] = await _lead_site_plan_png(db, q.lead_id)
    pdf = _proposal.build_pdf(data)
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="Proposal-{q.number}.pdf"'})


@public_router.get("/{token}/site-plan.pdf")
async def public_site_plan_pdf(token: str, db: AsyncSession = Depends(get_db)):
    from services import object_storage
    from routers.measurements import _latest_site_plan_rev
    q = await _load(db, token)
    rev = await _latest_site_plan_rev(db, q.lead_id)
    key = (rev.site_plan or {}).get("pdf_key") if rev else None
    if not key:
        raise HTTPException(status_code=404, detail="No site plan available for this proposal.")
    data = object_storage.get_object(key)
    return StreamingResponse(iter([data]), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="site-plan.pdf"'})
