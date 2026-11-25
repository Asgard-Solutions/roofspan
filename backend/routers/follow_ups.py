from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import LeadFollowUp, Lead, User
from core import get_current_user, require_roles, FIELD_ROLES, log_action
from services import follow_ups as fu

router = APIRouter(prefix="/api", tags=["follow-ups"])


class FollowUpIn(BaseModel):
    id: str | None = None  # client-generated id so Field can create offline and complete it before sync
    kind: str = "call"
    due_at: datetime | None = None
    note: str | None = None
    status: str = "open"  # open = scheduled follow-up, done = logged contact
    outcome: str | None = None


class FollowUpPatch(BaseModel):
    kind: str | None = None
    due_at: datetime | None = None
    note: str | None = None
    status: str | None = None
    outcome: str | None = None


def _utc(d: datetime | None):
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _check_kind(k):
    if k is not None and k not in fu.KINDS:
        raise HTTPException(status_code=422, detail=f"Invalid follow-up type '{k}'. Allowed: {', '.join(fu.KINDS)}")


@router.get("/lead-statuses")
async def lead_statuses(user: User = Depends(get_current_user)):
    return {"statuses": list(fu.LEAD_STATUSES), "open": list(fu.OPEN_LEAD_STATUSES), "kinds": list(fu.KINDS),
            "kind_labels": fu.KIND_LABELS}


@router.get("/leads/{lead_id}/follow-ups")
async def list_follow_ups(lead_id: str, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    lead = await fu.assert_lead(db, lead_id, user)
    rows = (await db.execute(select(LeadFollowUp).where(LeadFollowUp.lead_id == lead.id)
                             .order_by(LeadFollowUp.due_at.desc()))).scalars().all()
    return [fu.fu_out(f) for f in rows]


@router.post("/leads/{lead_id}/follow-ups", status_code=201)
async def create_follow_up(lead_id: str, payload: FollowUpIn, request: Request, user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    lead = await fu.assert_lead(db, lead_id, user)
    _check_kind(payload.kind)
    if payload.status not in ("open", "done"):
        raise HTTPException(status_code=422, detail="New follow-ups must be 'open' (scheduled) or 'done' (logged contact)")
    if payload.status == "open" and not payload.due_at:
        raise HTTPException(status_code=422, detail="Choose when the follow-up is due")
    fid = fu.parse_uuid(payload.id, "follow-up") if payload.id else None
    if fid:
        existing = await db.get(LeadFollowUp, fid)
        if existing:  # offline replay of the same create
            if existing.lead_id != lead.id:
                raise HTTPException(status_code=409, detail="This follow-up id belongs to another lead")
            return fu.fu_out(existing)
    now = datetime.now(timezone.utc)
    f = LeadFollowUp(lead_id=lead.id, kind=payload.kind, due_at=_utc(payload.due_at) or now, note=payload.note,
                     status=payload.status, outcome=payload.outcome, created_by=user.email)
    if fid:
        f.id = fid
    if payload.status == "done":
        f.completed_at, f.completed_by = now, user.email
        if lead.status == "new":
            lead.status = "contacted"
    db.add(f)
    await db.commit()
    await db.refresh(f)
    await log_action(db, user=user, action="followup.log" if f.status == "done" else "followup.create", entity_type="lead",
                     entity_id=lead.id, detail={"follow_up_id": str(f.id), "kind": f.kind, "due_at": f.due_at.isoformat()}, request=request)
    return fu.fu_out(f)


@router.patch("/follow-ups/{follow_up_id}")
async def update_follow_up(follow_up_id: str, payload: FollowUpPatch, request: Request, if_match: str | None = Header(None),
                           user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    f = await db.get(LeadFollowUp, fu.parse_uuid(follow_up_id, "follow-up"))
    if not f:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    lead = await fu.assert_lead(db, f.lead_id, user)
    data = payload.model_dump(exclude_unset=True)
    _check_kind(data.get("kind"))
    if "status" in data and data["status"] not in ("open", "done", "cancelled"):
        raise HTTPException(status_code=422, detail="Status must be open, done or cancelled")
    if "due_at" in data and data["due_at"] is None:
        raise HTTPException(status_code=422, detail="A follow-up needs a due date")
    if data.get("status") and data["status"] == f.status and f.status != "open" and len(data) == 1:
        return fu.fu_out(f)  # repeat complete/cancel (offline replay) is a no-op
    token = fu.fu_out(f)["if_match"]
    if if_match and token and if_match != token:
        raise HTTPException(status_code=409, detail={"message": "This follow-up changed since your copy.", "server": fu.fu_out(f)})
    if "due_at" in data:
        data["due_at"] = _utc(data["due_at"])
    for k, v in data.items():
        setattr(f, k, v)
    if data.get("status") == "done":
        f.completed_at, f.completed_by = datetime.now(timezone.utc), user.email
        if lead.status == "new":
            lead.status = "contacted"
    elif data.get("status") == "open":
        f.completed_at = f.completed_by = None
    await db.commit()
    await db.refresh(f)
    await log_action(db, user=user, action=f"followup.{data.get('status') or 'update'}", entity_type="lead", entity_id=lead.id,
                     detail={"follow_up_id": str(f.id), "fields": sorted(data.keys())}, request=request)
    return fu.fu_out(f)


@router.get("/mobile/my-day")
async def my_day(tz: str | None = Query(None), user: User = Depends(require_roles(*FIELD_ROLES)), db: AsyncSession = Depends(get_db)):
    """Field 'My Day': the same attention lists as Office Home, always for the leads assigned to the caller."""
    data = await fu.sales_attention(db, user, tz, only_mine=True, limit=50)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return data
