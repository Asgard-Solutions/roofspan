"""Sales follow-ups: one shared rule set for Office and Field (statuses, due/overdue, next action, attention)."""
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Lead, LeadFollowUp, Inspection, Quote, User

LEAD_STATUSES = ("new", "contacted", "qualified", "won", "lost")
OPEN_LEAD_STATUSES = ("new", "contacted", "qualified")
SYSTEM_STATUSES = ("archived",)
KINDS = ("call", "text", "email", "visit", "meeting", "other")
KIND_LABELS = {"call": "Call", "text": "Text", "email": "Email", "visit": "Visit", "meeting": "Meeting", "other": "Follow up"}
PROPOSAL_STALE_DAYS = 3
PROPOSAL_EXPIRY_DAYS = 3


def validate_status(value, allow_archived: bool = False):
    if value is None:
        return value
    ok = LEAD_STATUSES + (SYSTEM_STATUSES if allow_archived else ())
    if value not in ok:
        raise HTTPException(status_code=422, detail=f"Invalid lead status '{value}'. Allowed: {', '.join(LEAD_STATUSES)}")
    return value


def day_bounds(tz: str | None):
    try:
        z = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        z = timezone.utc
    now = datetime.now(z)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _iso(d):
    return d.isoformat() if d else None


def fu_out(f: LeadFollowUp) -> dict:
    return {"id": str(f.id), "lead_id": str(f.lead_id), "kind": f.kind, "kind_label": KIND_LABELS.get(f.kind, f.kind),
            "due_at": _iso(f.due_at), "note": f.note, "status": f.status, "outcome": f.outcome,
            "completed_at": _iso(f.completed_at), "completed_by": f.completed_by, "created_by": f.created_by,
            "created_at": _iso(f.created_at), "if_match": _iso(f.updated_at or f.created_at)}


def parse_uuid(v, what="record"):
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail=f"{what.capitalize()} not found")


async def lead_facts(db: AsyncSession, lead_ids: list) -> dict:
    """Per lead: earliest open follow-up, open follow-up count, next scheduled inspection, proposal facts."""
    out = {lid: {"next_fu": None, "open_fu": 0, "insp": None, "drafts": 0, "sent": 0} for lid in lead_ids}
    if not lead_ids:
        return out
    fus = (await db.execute(select(LeadFollowUp).where(LeadFollowUp.lead_id.in_(lead_ids), LeadFollowUp.status == "open")
                            .order_by(LeadFollowUp.due_at.asc()))).scalars().all()
    for f in fus:
        o = out[f.lead_id]
        o["open_fu"] += 1
        if o["next_fu"] is None:
            o["next_fu"] = f
    ins = (await db.execute(select(Inspection).where(Inspection.lead_id.in_(lead_ids), Inspection.status == "scheduled")
                            .order_by(Inspection.inspection_date.asc().nullslast()))).scalars().all()
    for i in ins:
        if out[i.lead_id]["insp"] is None:
            out[i.lead_id]["insp"] = i
    qs = (await db.execute(select(Quote.lead_id, Quote.status).where(Quote.lead_id.in_(lead_ids)))).all()
    for lid, st in qs:
        if st == "draft":
            out[lid]["drafts"] += 1
        elif st == "sent":
            out[lid]["sent"] += 1
    return out


def next_action(lead: Lead, f: dict, today_start: datetime, today_end: datetime) -> dict | None:
    """The single next-action wording shown in Office and Field."""
    if lead.status not in OPEN_LEAD_STATUSES:
        return None
    fu = f["next_fu"]
    if fu:
        when = "overdue" if fu.due_at < today_start else "today" if fu.due_at < today_end else "upcoming"
        return {"text": f"{KIND_LABELS.get(fu.kind, 'Follow up')}: {fu.note}" if fu.note else KIND_LABELS.get(fu.kind, "Follow up"),
                "due_at": _iso(fu.due_at), "when": when, "type": "follow_up"}
    insp = f["insp"]
    if insp:
        when = "overdue" if insp.inspection_date and insp.inspection_date < today_start else \
            "today" if insp.inspection_date and insp.inspection_date < today_end else "upcoming"
        return {"text": "Inspection booked", "due_at": _iso(insp.inspection_date), "when": when, "type": "inspection"}
    if f["sent"]:
        text = "Follow up on the proposal"
    elif f["drafts"]:
        text = "Send the proposal"
    elif lead.status == "new":
        text = "Make first contact"
    elif lead.status == "contacted":
        text = "Book the inspection"
    else:
        text = "Schedule a follow-up"
    return {"text": text, "due_at": None, "when": "none", "type": "suggestion"}


async def enrich(db: AsyncSession, leads: list, tz: str | None) -> dict:
    s, e = day_bounds(tz)
    facts = await lead_facts(db, [l.id for l in leads])
    return {l.id: {"next_action": next_action(l, facts[l.id], s, e), "open_follow_ups": facts[l.id]["open_fu"]} for l in leads}


async def assert_lead(db: AsyncSession, lead_id, user) -> Lead:
    lead = await db.get(Lead, parse_uuid(lead_id, "lead"))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if user.role == "sales" and lead.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    return lead


def _row(title, subtitle, date, link, **kw):
    return {"title": title, "subtitle": subtitle, "date": _iso(date), "link": link, **kw}


async def sales_attention(db: AsyncSession, user: User, tz: str | None, only_mine: bool, limit: int = 6) -> dict:
    """Follow-up, inspection and proposal attention lists. Sales (or only_mine) see only their assigned leads."""
    now = datetime.now(timezone.utc)
    s, e = day_bounds(tz)
    mine = user.role == "sales" or only_mine
    manage = user.role in ("owner", "administrator", "office") and not only_mine

    fq = (select(LeadFollowUp, Lead).join(Lead, Lead.id == LeadFollowUp.lead_id)
          .where(LeadFollowUp.status == "open", LeadFollowUp.due_at < e, Lead.status.in_(OPEN_LEAD_STATUSES))
          .order_by(LeadFollowUp.due_at.asc()))
    if mine:
        fq = fq.where(Lead.assigned_user_id == user.id)
    due = (await db.execute(fq)).all()
    overdue = [(f, l) for f, l in due if f.due_at < s]
    today = [(f, l) for f, l in due if f.due_at >= s]

    def fu_row(f, l, when):
        label = KIND_LABELS.get(f.kind, "Follow up")
        return _row(l.name or l.address or "Unnamed lead", f"{label}{': ' + f.note if f.note else ''}", f.due_at,
                    f"/leads/{l.id}", id=str(f.id), lead_id=str(l.id), when=when, kind=f.kind,
                    assigned_user_id=str(l.assigned_user_id) if l.assigned_user_id else None)

    iq = (select(Inspection, Lead).join(Lead, Lead.id == Inspection.lead_id)
          .where(Inspection.status == "scheduled", Inspection.inspection_date < s + timedelta(days=8))
          .order_by(Inspection.inspection_date.asc()))
    if mine:
        iq = iq.where(Lead.assigned_user_id == user.id)
    insp = (await db.execute(iq)).all()

    qq = (select(Quote, Lead).join(Lead, Lead.id == Quote.lead_id).where(Quote.status.in_(("draft", "sent")),
          Lead.status.in_(OPEN_LEAD_STATUSES)).order_by(Quote.created_at.asc()))
    if mine:
        qq = qq.where(Lead.assigned_user_id == user.id)
    stale = now - timedelta(days=PROPOSAL_STALE_DAYS)
    props = []
    for q, l in (await db.execute(qq)).all():
        reason = None
        if q.expiration_date and now <= q.expiration_date <= now + timedelta(days=PROPOSAL_EXPIRY_DAYS):
            reason = "Expires soon"
        elif q.status == "sent" and (q.issue_date or q.updated_at or q.created_at) < stale:
            reason = "No answer for 3+ days"
        elif q.status == "draft" and q.created_at < stale:
            reason = "Not sent for 3+ days"
        if reason:
            props.append(_row(q.number, f"{l.name} · {reason}", q.expiration_date if reason == "Expires soon" else (q.issue_date or q.created_at),
                              f"/leads/{l.id}", id=str(q.id), lead_id=str(l.id), amount=q.total, reason=reason, status=q.status))

    lq = select(Lead).where(Lead.status.in_(OPEN_LEAD_STATUSES)).order_by(Lead.created_at.asc())
    if mine:
        lq = lq.where(Lead.assigned_user_id == user.id)
    open_leads = (await db.execute(lq)).scalars().all()
    facts = await lead_facts(db, [l.id for l in open_leads])
    no_fu = [l for l in open_leads if not facts[l.id]["next_fu"] and not facts[l.id]["insp"]]

    out = {
        "follow_ups": {"count": len(due), "overdue_count": len(overdue), "today_count": len(today),
                       "items": ([fu_row(f, l, "overdue") for f, l in overdue] + [fu_row(f, l, "today") for f, l in today])[:limit]},
        "inspections": {"count": len(insp), "items": [
            _row((l.name if l else None) or "Inspection", (i.inspector and f"with {i.inspector}") or (l.address if l else None),
                 i.inspection_date, f"/leads/{i.lead_id}", id=str(i.id), lead_id=str(i.lead_id),
                 when="overdue" if i.inspection_date and i.inspection_date < s else "today" if i.inspection_date and i.inspection_date < e else "upcoming")
            for i, l in insp[:limit]]},
        "proposals": {"count": len(props), "total": round(sum(float(p["amount"] or 0) for p in props), 2), "items": props[:limit]},
        "no_follow_up": {"count": len(no_fu), "items": [
            _row(l.name or l.address or "Unnamed lead", next_action(l, facts[l.id], s, e)["text"], l.created_at, f"/leads/{l.id}",
                 id=str(l.id), lead_id=str(l.id), status=l.status) for l in no_fu[:limit]]},
    }
    if manage:
        unassigned = [l for l in open_leads if not l.assigned_user_id]
        by = {}
        for f, l in overdue:
            by[l.assigned_user_id] = by.get(l.assigned_user_id, 0) + 1
        names = {}
        ids = [k for k in by if k]
        if ids:
            names = {u.id: (u.full_name or u.email) for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()}
        out["unassigned"] = {"count": len(unassigned), "items": [
            _row(l.name or l.address or "Unnamed lead", l.address, l.created_at, f"/leads/{l.id}", id=str(l.id), status=l.status)
            for l in unassigned[:limit]]}
        out["overdue_by_rep"] = sorted([{"user_id": str(k) if k else None, "name": names.get(k, "Unassigned"), "count": v}
                                        for k, v in by.items()], key=lambda r: -r["count"])
    return out


INSPECTION_STATUSES = ("scheduled", "completed", "cancelled")
_RESULT_FIELDS = ("findings", "roof_condition", "recommended_work", "measurements")


def inspection_status(data: dict, current_status: str | None = None, current_date=None) -> str | None:
    """Booked inspections are 'scheduled'; recording any results completes them. Returns the status to store."""
    st = data.get("status")
    if st is not None and st not in INSPECTION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid inspection status '{st}'")
    if st == "scheduled" and not (data.get("inspection_date") or current_date):
        raise HTTPException(status_code=422, detail="Choose a date and time for the inspection")
    if st is None and current_status == "scheduled" and any(data.get(k) for k in _RESULT_FIELDS):
        return "completed"
    return st
