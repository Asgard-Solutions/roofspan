"""Purchasing / Inventory intelligence dashboard — aggregates REAL system data via existing services
(inventory_core, job_planning, reporting). Cost/value figures are gated to management roles at the
router. No metric is recomputed with a different formula than its source module."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Material, PurchaseOrder, POLineItem, Job, JobMaterial
from services import inventory_core as inv_core
from services import job_planning as jp

OPEN_PO_STATUSES = ("draft", "ready_for_review", "ordered", "submitted", "acknowledged", "scheduled", "partially_received", "backordered")
Z = Decimal("0")


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


async def purchasing_dashboard(db: AsyncSession, include_cost: bool, only_user_id=None) -> dict:
    mats = (await db.execute(select(Material).where(Material.active.is_(True)))).scalars().all()

    inv_value = Z
    reserved_qty = 0.0
    reserved_value = Z
    low_stock = 0
    for m in mats:
        q = await inv_core.compute_quantities(db, m)
        avg = _d(m.avg_cost) if m.avg_cost is not None else Z
        inv_value += _d(q["on_hand"]) * avg
        reserved_qty += q["reserved"]
        reserved_value += _d(q["reserved"]) * avg
        thr = float(m.reorder_threshold or 0)
        if thr > 0 and q["projected"] < thr:
            low_stock += 1

    # Open POs (exclude cancelled/received); committed value + incoming-this-week from expected_date.
    pos = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES)))).scalars().all()
    open_po_count = len(pos)
    committed_value = Z
    incoming_week = 0
    backordered = 0
    week = datetime.now(timezone.utc) + timedelta(days=7)
    now = datetime.now(timezone.utc)
    for po in pos:
        committed_value += _d(po.total)
        if po.expected_date and now <= po.expected_date <= week:
            incoming_week += 1
        if po.status == "backordered":
            backordered += 1

    # Jobs needing materials (real shortage via job_planning readiness).
    jstmt = select(Job).where(Job.status.in_(("scheduled", "in_progress", "active", "created")))
    if only_user_id is not None:
        jstmt = jstmt.where(Job.assigned_user_id == only_user_id)
    active_jobs = (await db.execute(jstmt)).scalars().all()
    jobs_short = 0
    actions = []
    for j in active_jobs[:200]:
        jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == j.id))).scalars().all()
        shortfall = 0.0
        for jm in jms:
            r = await jp.rollup(db, jm)
            if r.get("shortage", 0) > 0:
                shortfall += r["shortage"]
        if shortfall > 0:
            jobs_short += 1
            if len(actions) < 25:
                actions.append({"type": "job_shortage", "severity": "warn",
                                "message": f"{j.number} needs {round(shortfall, 2)} unit(s) of material",
                                "link": f"/jobs/{j.id}"})

    # PO-derived actions (company purchasing; not shown to sales-scoped views)
    for po in (pos if only_user_id is None else []):
        if po.status == "partially_received" and len(actions) < 40:
            actions.append({"type": "po_partial", "severity": "info",
                            "message": f"{po.number} partially received", "link": f"/purchase-orders/{po.id}"})
        elif po.status == "backordered" and len(actions) < 40:
            actions.append({"type": "po_backordered", "severity": "warn",
                            "message": f"{po.number} backordered", "link": f"/purchase-orders/{po.id}"})
        elif po.expected_date and po.expected_date < now and po.status not in ("received", "cancelled") and len(actions) < 40:
            actions.append({"type": "po_overdue", "severity": "warn",
                            "message": f"{po.number} delivery overdue", "link": f"/purchase-orders/{po.id}"})

    cards = {
        "low_stock_items": low_stock,
        "reserved_quantity": round(reserved_qty, 3),
        "open_purchase_orders": open_po_count,
        "incoming_this_week": incoming_week,
        "jobs_needing_materials": jobs_short,
        "backordered_items": backordered,
    }
    if include_cost:
        cards["inventory_value"] = float(inv_value.quantize(Decimal("0.01")))          # operational average cost, not GAAP
        cards["reserved_value"] = float(reserved_value.quantize(Decimal("0.01")))
        cards["open_po_committed_value"] = float(committed_value.quantize(Decimal("0.01")))
    return {"cards": cards, "action_required": actions, "cost_visible": include_cost}


def _iso(d):
    return d.isoformat() if d else None


async def attention(db: AsyncSession, user, include_money: bool) -> dict:
    from models import Lead, Inspection, Quote, Invoice
    now = datetime.now(timezone.utc)
    sales = user.role == "sales"

    lq = select(Lead).where(Lead.status.in_(("new", "working"))).order_by(Lead.updated_at.asc())
    if sales:
        lq = lq.where(Lead.assigned_user_id == user.id)
    stale = now - timedelta(days=3)
    follow = [l for l in (await db.execute(lq)).scalars().all()
              if l.status == "new" or (l.updated_at and l.updated_at < stale)]

    iq = (select(Inspection, Lead).outerjoin(Lead, Lead.id == Inspection.lead_id)
          .where(Inspection.inspection_date >= now - timedelta(hours=12), Inspection.inspection_date <= now + timedelta(days=7))
          .order_by(Inspection.inspection_date.asc()))
    if sales:
        iq = iq.where(Lead.assigned_user_id == user.id)
    insp = (await db.execute(iq)).all()

    qq = (select(Quote, Lead).outerjoin(Lead, Lead.id == Quote.lead_id)
          .where(Quote.status == "sent").order_by(Quote.issue_date.asc().nullslast()))
    if sales:
        qq = qq.where(Lead.assigned_user_id == user.id)
    quotes = (await db.execute(qq)).all()

    jq = (select(Job).where(Job.status.in_(("scheduled", "in_progress")))
          .order_by(Job.scheduled_start.asc().nullslast()))
    if sales:
        jq = jq.where(Job.assigned_user_id == user.id)
    jobs = (await db.execute(jq)).scalars().all()

    out = {
        "follow_ups": {"count": len(follow), "items": [
            {"id": str(l.id), "title": l.name or l.address or "Unnamed lead", "subtitle": l.address,
             "status": l.status, "date": _iso(l.updated_at), "link": f"/leads/{l.id}"} for l in follow[:6]]},
        "inspections": {"count": len(insp), "items": [
            {"id": str(i.id), "title": (ld.name if ld else None) or i.inspector or "Inspection",
             "subtitle": ld.address if ld else None, "date": _iso(i.inspection_date),
             "link": f"/leads/{i.lead_id}" if i.lead_id else "/leads"} for i, ld in insp[:6]]},
        "proposals": {"count": len(quotes), "total": round(sum(float(q.total or 0) for q, _ in quotes), 2), "items": [
            {"id": str(q.id), "title": q.number, "subtitle": ld.name if ld else None, "amount": q.total,
             "date": _iso(q.issue_date), "link": f"/leads/{q.lead_id}" if q.lead_id else f"/quotes/{q.id}/proposal"}
            for q, ld in quotes[:6]]},
        "jobs": {"count": len(jobs), "items": [
            {"id": str(j.id), "title": j.number, "subtitle": j.scope, "status": j.status,
             "date": _iso(j.scheduled_start), "link": f"/jobs/{j.id}"} for j in jobs[:6]]},
        "money": None,
    }
    if include_money:
        invs = (await db.execute(select(Invoice).where(Invoice.status == "issued").order_by(Invoice.due_date.asc().nullslast()))).scalars().all()
        overdue = [i for i in invs if i.due_date and i.due_date < now]
        out["money"] = {
            "open_count": len(invs), "open_total": round(sum(float(i.total or 0) for i in invs), 2),
            "overdue_count": len(overdue), "overdue_total": round(sum(float(i.total or 0) for i in overdue), 2),
            "items": [{"id": str(i.id), "title": i.number, "amount": i.total, "date": _iso(i.due_date),
                       "overdue": bool(i.due_date and i.due_date < now), "link": "/billing"} for i in (overdue or invs)[:6]],
        }
    return out
