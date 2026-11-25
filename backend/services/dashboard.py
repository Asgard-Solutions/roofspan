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
    qs = await inv_core.batch_quantities(db, mats)
    for m in mats:
        q = qs[m.id]
        avg = _d(m.avg_cost) if m.avg_cost is not None else Z
        inv_value += _d(q["on_hand"]) * avg
        reserved_qty += q["reserved"]
        reserved_value += _d(q["reserved"]) * avg
        if inv_core.is_low_stock(q["available"], m.reorder_threshold):
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
    short = await jp.shortages_by_job(db, [j.id for j in active_jobs])
    jobs_short = 0
    actions = []
    for j in active_jobs:
        shortfall = short.get(j.id, 0)
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


async def attention(db: AsyncSession, user, include_money: bool, tz: str | None = None) -> dict:
    from models import Invoice
    from services.follow_ups import sales_attention
    now = datetime.now(timezone.utc)
    sales = user.role == "sales"

    jq = (select(Job).where(Job.status.in_(("scheduled", "in_progress")))
          .order_by(Job.scheduled_start.asc().nullslast()))
    if sales:
        jq = jq.where(Job.assigned_user_id == user.id)
    jobs = (await db.execute(jq)).scalars().all()

    out = {
        **(await sales_attention(db, user, tz, only_mine=False)),
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
