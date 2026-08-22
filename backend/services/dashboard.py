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


async def purchasing_dashboard(db: AsyncSession, include_cost: bool) -> dict:
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
    active_jobs = (await db.execute(select(Job).where(Job.status.in_(("scheduled", "in_progress", "active", "created"))))).scalars().all()
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

    # PO-derived actions
    for po in pos:
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
        cards["inventory_value"] = float(inv_value.quantize(Decimal("0.01")))          # operational (MWAC), not GAAP
        cards["reserved_value"] = float(reserved_value.quantize(Decimal("0.01")))
        cards["open_po_committed_value"] = float(committed_value.quantize(Decimal("0.01")))
    return {"cards": cards, "action_required": actions, "cost_visible": include_cost}
