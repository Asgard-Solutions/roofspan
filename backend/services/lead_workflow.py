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


async def lead_workflows(db: AsyncSession, leads: list) -> dict:
    """Batched facts + stage for many leads (same rules as a single lead; used by lists and My Day)."""
    ids = [l.id for l in leads]
    f = {l.id: {"has_customer": bool(l.customer_id), "inspections": 0, "inspections_scheduled": 0, "has_measurements": False,
                "estimates": 0, "quotes": 0, "quotes_draft": 0, "quotes_sent": 0, "quotes_accepted": 0, "quotes_declined": 0,
                "jobs": 0, "jobs_scheduled": 0, "jobs_completed": 0, "invoices": 0, "invoices_paid": 0, "invoices_draft": 0,
                "first_job_id": None} for l in leads}
    if not ids:
        return {}
    q2lead = {}
    for qid, lid, st in (await db.execute(select(Quote.id, Quote.lead_id, Quote.status).where(Quote.lead_id.in_(ids)))).all():
        q2lead[qid] = lid
        x = f[lid]
        x["quotes"] += 1
        if st in ("draft", "sent", "accepted", "declined"):
            x[f"quotes_{st}"] += 1
    j2lead = {}
    if q2lead:
        for jid, qid, st, start in (await db.execute(select(Job.id, Job.quote_id, Job.status, Job.scheduled_start)
                                                     .where(Job.quote_id.in_(list(q2lead))).order_by(Job.created_at.asc()))).all():
            lid = q2lead[qid]
            j2lead[jid] = lid
            x = f[lid]
            x["jobs"] += 1
            x["jobs_scheduled"] += start is not None
            x["jobs_completed"] += st == "completed"
            x["first_job_id"] = x["first_job_id"] or str(jid)
        conds = [Invoice.quote_id.in_(list(q2lead))] + ([Invoice.job_id.in_(list(j2lead))] if j2lead else [])
        for qid, jid, st in (await db.execute(select(Invoice.quote_id, Invoice.job_id, Invoice.status)
                                              .where(or_(*conds), Invoice.status != "void"))).all():
            lid = q2lead.get(qid) or j2lead.get(jid)
            if lid is None:
                continue
            x = f[lid]
            x["invoices"] += 1
            x["invoices_paid"] += st == "paid"
            x["invoices_draft"] += st == "draft"
    for lid, st, n in (await db.execute(select(Inspection.lead_id, Inspection.status, func.count(Inspection.id))
                                        .where(Inspection.lead_id.in_(ids)).group_by(Inspection.lead_id, Inspection.status))).all():
        if st == "completed":
            f[lid]["inspections"] = n
        elif st == "scheduled":
            f[lid]["inspections_scheduled"] = n
    for (lid,) in (await db.execute(select(MeasurementSet.lead_id).join(MeasurementRevision, MeasurementRevision.set_id == MeasurementSet.id)
                                    .where(MeasurementSet.lead_id.in_(ids)).distinct())).all():
        f[lid]["has_measurements"] = True
    for lid, n in (await db.execute(select(Estimate.lead_id, func.count(Estimate.id)).where(Estimate.lead_id.in_(ids)).group_by(Estimate.lead_id))).all():
        f[lid]["estimates"] = n
    return {lid: {"stage": derive_stage(x), "facts": x} for lid, x in f.items()}


def stage_action(wf: dict, is_manage: bool) -> dict:
    """Stage guidance (the text the Office Lead Detail banner always used), now shared with Field and lists."""
    f, stage = wf["facts"], wf["stage"]
    if stage == "overview":
        return {"text": "Create the customer record to start the sale.", "stage": "overview"}
    if stage == "inspection":
        if not f["inspections"]:
            return {"text": "Inspection is booked. Record the results after the visit." if f["inspections_scheduled"] else "Book or record the roof inspection.", "stage": "inspection"}
        if not f["has_measurements"]:
            return {"text": "Measure the roof.", "stage": "inspection"}
        return {"text": "Build the estimate.", "stage": "estimate"}
    if stage == "estimate":
        if not f["quotes"]:
            return {"text": "Turn the estimate into a proposal.", "stage": "estimate"}
        if f["quotes_sent"]:
            return {"text": "Waiting on the customer. Follow up, or record their decision." if is_manage else "Waiting on the customer. Follow up with them.", "stage": "estimate"}
        if f["quotes_draft"]:
            return {"text": "Send the proposal to the customer.", "stage": "estimate"}
        return {"text": "Proposal declined. Revise the estimate or close the lead.", "stage": "estimate"}
    if stage == "production":
        if not f["jobs_scheduled"]:
            return {"text": "Schedule the job.", "stage": "production", "jobId": f["first_job_id"]}
        return {"text": "Job is underway. Track it on the job page.", "stage": "production", "jobId": f["first_job_id"]}
    if not f["invoices"]:
        return {"text": "Create the invoice." if is_manage else "Work complete. The office handles invoicing.", "stage": "billing"}
    if f["invoices_draft"]:
        return {"text": "Send the invoice to the customer." if is_manage else "The office is preparing the invoice.", "stage": "billing"}
    if f["invoices_paid"] < f["invoices"]:
        return {"text": "Collect the balance due.", "stage": "billing"}
    return {"text": "Paid in full. Nothing left to do.", "stage": "billing", "done": True}


async def lead_workflow(db: AsyncSession, lead: Lead) -> dict:
    wf = (await lead_workflows(db, [lead]))[lead.id]
    return {"stage": wf["stage"], "stage_index": STAGES.index(wf["stage"]), "stages": STAGES, "facts": wf["facts"]}
