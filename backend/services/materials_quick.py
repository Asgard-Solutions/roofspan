"""Daily Materials quick filters. One server-side definition so counts and filtered lists always agree.

short_for_jobs  : material has a JobMaterial row on an active job with shortage > 0
                  (planned - reserved - incoming on that job's open POs; same formula as Job Detail).
needs_ordering  : short_for_jobs, OR reorder point reached (threshold > 0 and On Hand + On Order - Required < threshold,
                  the same rule as Reorder suggestions).
on_order        : outstanding quantity on open purchase orders > 0.
arriving_week   : outstanding quantity on an open PO whose expected date is within the next 7 days (or already past).
Only active materials are counted.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Material, JobMaterial, Job, PurchaseOrder, POLineItem
from services import job_planning as jp
from services.inventory_core import _OPEN_PO_STATUSES, _ACTIVE_JOB_STATUSES_EXCLUDED

QUICK_KEYS = ("short_for_jobs", "needs_ordering", "on_order", "arriving_week")
_OUTSTANDING = func.greatest(POLineItem.quantity - POLineItem.received_quantity, 0)


async def quick_sets(db: AsyncSession) -> dict:
    mats = {str(r[0]): r for r in (await db.execute(
        select(Material.id, Material.quantity_on_hand, Material.reorder_threshold).where(Material.active.is_(True)))).all()}
    job_ids = (await db.execute(select(Job.id).where(Job.status.notin_(_ACTIVE_JOB_STATUSES_EXCLUDED)))).scalars().all()
    short = {str(m) for _j, m, s in await jp.shortage_rows(db, job_ids) if s > 0 and m is not None} & mats.keys()
    on_order = {str(m): float(q) for m, q in (await db.execute(
        select(POLineItem.material_id, func.sum(_OUTSTANDING)).join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(PurchaseOrder.status.in_(_OPEN_PO_STATUSES), POLineItem.material_id.isnot(None))
        .group_by(POLineItem.material_id))).all()}
    required = {str(m): float(q or 0) for m, q in (await db.execute(
        select(JobMaterial.material_id, func.sum(JobMaterial.planned_quantity)).join(Job, Job.id == JobMaterial.job_id)
        .where(Job.status.notin_(_ACTIVE_JOB_STATUSES_EXCLUDED)).group_by(JobMaterial.material_id))).all()}
    reorder = set()
    for mid, (_id, on_hand, thr) in mats.items():
        thr = float(thr or 0)
        if thr > 0 and float(on_hand or 0) + on_order.get(mid, 0) - required.get(mid, 0) < thr:
            reorder.add(mid)
    soon = datetime.now(timezone.utc) + timedelta(days=7)
    arriving = {str(m) for m in (await db.execute(
        select(POLineItem.material_id).join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(PurchaseOrder.status.in_(_OPEN_PO_STATUSES), PurchaseOrder.expected_date.isnot(None),
               PurchaseOrder.expected_date <= soon, _OUTSTANDING > 0, POLineItem.material_id.isnot(None)))).scalars().all()}
    return {"short_for_jobs": short, "needs_ordering": short | reorder,
            "on_order": {m for m, q in on_order.items() if q > 0} & mats.keys(), "arriving_week": arriving & mats.keys()}
