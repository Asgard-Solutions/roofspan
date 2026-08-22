"""Job Material Automation & Smart Purchasing — server-authoritative operational logic.

Quantities (per job+material):
  Required = JobMaterial.planned_quantity (snapshot from accepted quote/package; never recalculated)
  Reserved = |Σ job_reservation ledger deltas| for (job, material)
  Issued   = |Σ job_issue| ;  Returned = |Σ job_return|
  Ordered  = Σ POLineItem.quantity for POs linked to this job (this material)
  Received = Σ POLineItem.received_quantity (same)
  JobIncoming = Σ max(quantity - received_quantity, 0) over OPEN POs linked to this job (this material)
  Shortage = max(Required - Reserved - JobIncoming, 0)
  Remaining = max(Required - Issued, 0)
Reservation raises Reserved / lowers Available; it NEVER changes physical On Hand.
Only POs explicitly linked to the job (PurchaseOrder.job_id) count toward that job's incoming.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import (JobMaterial, Material, InventoryTxn, PurchaseOrder, POLineItem, Supplier,
                    SupplierMaterial, Quote, QuoteLineItem)
from services import inventory_core as inv

_OPEN = inv._OPEN_PO_STATUSES


def _r3(v):
    return round(float(v or 0), 3)


async def _sum_txn(db, job_id, material_id, reason):
    v = (await db.execute(select(func.coalesce(func.sum(InventoryTxn.delta), 0)).where(
        InventoryTxn.job_id == job_id, InventoryTxn.material_id == material_id, InventoryTxn.reason == reason))).scalar() or 0
    return abs(float(v))


async def rollup(db: AsyncSession, jm: JobMaterial) -> dict:
    m = await db.get(Material, jm.material_id)
    required = _r3(jm.planned_quantity)
    reserved = _r3(await _sum_txn(db, jm.job_id, jm.material_id, "job_reservation"))
    issued = _r3(await _sum_txn(db, jm.job_id, jm.material_id, "job_issue"))
    returned = _r3(await _sum_txn(db, jm.job_id, jm.material_id, "job_return"))
    # PO quantities linked to THIS job + material
    rows = (await db.execute(
        select(POLineItem.quantity, POLineItem.received_quantity, PurchaseOrder.status)
        .join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(PurchaseOrder.job_id == jm.job_id, POLineItem.material_id == jm.material_id,
               PurchaseOrder.status != "cancelled"))).all()
    ordered = _r3(sum(r[0] or 0 for r in rows))
    received = _r3(sum(r[1] or 0 for r in rows))
    job_incoming = _r3(sum(max((r[0] or 0) - (r[1] or 0), 0) for r in rows if r[2] in _OPEN))
    backordered = any(r[2] == "backordered" for r in rows)
    qty = await inv.compute_quantities(db, m) if m else {"on_hand": 0, "available": 0}
    available = _r3(qty.get("available", 0))
    shortage = _r3(max(required - reserved - job_incoming, 0))
    remaining = _r3(max(required - issued, 0))
    # readiness
    if backordered and shortage > 0:
        status = "backordered"
    elif shortage <= 0 and reserved >= required - 1e-6:
        status = "ready"
    elif shortage <= 0 and job_incoming > 0:
        status = "waiting_on_materials"
    elif reserved > 0 or received > 0:
        status = "partially_ready"
    else:
        status = "waiting_on_materials"
    return {"required": required, "reserved": reserved, "available": available, "shortage": shortage,
            "ordered": ordered, "received": received, "issued": issued, "returned": returned,
            "remaining": remaining, "on_hand": _r3(qty.get("on_hand", 0)), "status": status}


async def generate_from_quote(db: AsyncSession, job, user_email: str) -> dict:
    """Idempotent: create JobMaterial rows from the accepted quote/package. Skips lines already generated
    (keyed by source_quote_line_id). Only material-linked lines become requirements."""
    if not job.quote_id:
        return {"created": 0, "skipped": 0, "reason": "job has no linked quote"}
    q = await db.get(Quote, job.quote_id)
    if not q:
        return {"created": 0, "skipped": 0, "reason": "quote not found"}
    stmt = select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id)
    if q.multi_package:
        if not q.accepted_package_id:
            return {"created": 0, "skipped": 0, "reason": "multi-package quote has no accepted package"}
        stmt = stmt.where(QuoteLineItem.package_id == q.accepted_package_id)
    else:
        stmt = stmt.where(QuoteLineItem.package_id.is_(None))
    lines = (await db.execute(stmt.order_by(QuoteLineItem.sort))).scalars().all()
    existing = {str(r) for r in (await db.execute(
        select(JobMaterial.source_quote_line_id).where(JobMaterial.job_id == job.id))).scalars().all() if r}
    created = skipped = non_material = 0
    for ln in lines:
        if not ln.material_id:
            non_material += 1
            continue
        if str(ln.id) in existing:
            skipped += 1
            continue
        db.add(JobMaterial(job_id=job.id, material_id=ln.material_id, planned_quantity=ln.quantity,
                           unit=ln.unit, source_quote_id=q.id, source_quote_line_id=ln.id, notes="From accepted quote"))
        created += 1
    return {"created": created, "skipped": skipped, "non_material_lines": non_material}


async def reserve(db: AsyncSession, jm: JobMaterial, quantity: float | None, user_email: str) -> dict:
    """Reserve up to available; if quantity None reserve the full outstanding requirement (capped at available)."""
    m = await db.get(Material, jm.material_id)
    roll = await rollup(db, jm)
    outstanding = max(roll["required"] - roll["reserved"], 0)
    want = outstanding if quantity is None else min(float(quantity), outstanding)
    qty_state = await inv.compute_quantities(db, m)
    can = max(min(want, qty_state["available"]), 0)
    if can <= 0:
        return {"reserved": 0, "message": "Nothing available to reserve", **await rollup(db, jm)}
    db.add(InventoryTxn(material_id=jm.material_id, delta=-_r3(can), reason="job_reservation",
                        job_id=jm.job_id, note="Job reservation", created_by=user_email))
    await db.flush()
    return {"reserved": _r3(can), **await rollup(db, jm)}


async def release(db: AsyncSession, jm: JobMaterial, user_email: str) -> dict:
    roll = await rollup(db, jm)
    if roll["reserved"] <= 0:
        return {"released": 0, **roll}
    db.add(InventoryTxn(material_id=jm.material_id, delta=_r3(roll["reserved"]), reason="job_reservation",
                        job_id=jm.job_id, note="Release reservation", created_by=user_email))
    await db.flush()
    return {"released": roll["reserved"], **await rollup(db, jm)}


async def supplier_options(db: AsyncSession, material_id) -> list[dict]:
    rows = (await db.execute(
        select(SupplierMaterial, Supplier.name, Supplier.integration_provider, Supplier.default_branch)
        .outerjoin(Supplier, Supplier.id == SupplierMaterial.supplier_id)
        .where(SupplierMaterial.material_id == material_id, SupplierMaterial.active.is_(True))
        .order_by(SupplierMaterial.is_preferred.desc(), SupplierMaterial.current_cost.asc()))).all()
    out = []
    for sm, sname, prov, branch in rows:
        out.append({"supplier_material_id": str(sm.id), "supplier_id": str(sm.supplier_id) if sm.supplier_id else None,
                    "supplier_name": sname, "integration_provider": prov, "is_preferred": sm.is_preferred,
                    "current_cost": sm.current_cost, "price_status": sm.price_status,
                    "price_updated_at": sm.price_updated_at.isoformat() if sm.price_updated_at else None,
                    "supplier_uom": sm.supplier_uom, "conversion_factor": sm.conversion_factor,
                    "lead_time_days": sm.lead_time_days, "supplier_item_number": sm.supplier_item_number,
                    "default_branch": branch})
    return out


async def shortage_proposal(db: AsyncSession, job) -> dict:
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == job.id))).scalars().all()
    lines = []
    for jm in jms:
        roll = await rollup(db, jm)
        if roll["shortage"] <= 0:
            continue
        m = await db.get(Material, jm.material_id)
        opts = await supplier_options(db, jm.material_id)
        pref = next((o for o in opts if o["is_preferred"]), (opts[0] if opts else None))
        best = min([o for o in opts if o["current_cost"] is not None], key=lambda o: o["current_cost"], default=None)
        lines.append({"job_material_id": str(jm.id), "material_id": str(jm.material_id),
                      "material_name": m.name if m else "?", "unit": jm.unit or (m.unit if m else "ea"),
                      "shortage": roll["shortage"], "suggested_quantity": roll["shortage"],
                      "preferred": pref, "best_known": best, "suppliers": opts})
    return {"job_id": str(job.id), "job_number": job.number, "lines": lines}
