"""Deterministic Lead workflow stage, derived only from completed work (no stored stage field).

overview   -> no customer record yet
inspection -> customer exists, no estimate or quote yet
estimate   -> an estimate or quote exists, none accepted
production -> a quote was accepted (job created), job not completed, no invoice yet
billing    -> an invoice exists for this lead's work, or a job from it is completed
"""
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models import Lead, Inspection, Estimate, Quote, Job, Invoice, MeasurementSet, MeasurementRevision

STAGES = ["overview", "inspection", "estimate", "production", "billing"]


def derive_stage(f: dict) -> str:
    if f["invoices"] > 0 or f["jobs_completed"] > 0:
        return "billing"
    if f["quotes_accepted"] > 0 or f["jobs"] > 0:
        return "production"
    if f["estimates"] > 0 or f["quotes"] > 0:
        return "estimate"
    if f["has_customer"]:
        return "inspection"
    return "overview"


async def _count(db, stmt) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


async def lead_workflow(db: AsyncSession, lead: Lead) -> dict:
    quotes = (await db.execute(select(Quote.id, Quote.status).where(Quote.lead_id == lead.id))).all()
    qids = [q[0] for q in quotes]
    jobs = (await db.execute(select(Job.id, Job.status, Job.scheduled_start).where(Job.quote_id.in_(qids)))).all() if qids else []
    jids = [j[0] for j in jobs]
    inv_rows = []
    if qids or jids:
        conds = [Invoice.quote_id.in_(qids)] if qids else []
        if jids:
            conds.append(Invoice.job_id.in_(jids))
        inv_rows = (await db.execute(select(Invoice.status).where(or_(*conds), Invoice.status != "void"))).scalars().all()
    f = {
        "has_customer": bool(lead.customer_id),
        "inspections": await _count(db, select(func.count(Inspection.id)).where(Inspection.lead_id == lead.id)),
        "has_measurements": await _count(db, select(func.count(MeasurementRevision.id))
                                         .join(MeasurementSet, MeasurementSet.id == MeasurementRevision.set_id)
                                         .where(MeasurementSet.lead_id == lead.id)) > 0,
        "estimates": await _count(db, select(func.count(Estimate.id)).where(Estimate.lead_id == lead.id)),
        "quotes": len(quotes),
        "quotes_draft": sum(1 for q in quotes if q[1] == "draft"),
        "quotes_sent": sum(1 for q in quotes if q[1] == "sent"),
        "quotes_accepted": sum(1 for q in quotes if q[1] == "accepted"),
        "quotes_declined": sum(1 for q in quotes if q[1] == "declined"),
        "jobs": len(jobs),
        "jobs_scheduled": sum(1 for j in jobs if j[2] is not None),
        "jobs_completed": sum(1 for j in jobs if j[1] == "completed"),
        "invoices": len(inv_rows),
        "invoices_paid": sum(1 for s in inv_rows if s == "paid"),
        "invoices_draft": sum(1 for s in inv_rows if s == "draft"),
        "first_job_id": str(jids[0]) if jids else None,
    }
    stage = derive_stage(f)
    return {"stage": stage, "stage_index": STAGES.index(stage), "stages": STAGES, "facts": f}
