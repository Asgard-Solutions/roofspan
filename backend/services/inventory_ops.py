"""Advanced Inventory Operations — physical inventory lifecycle (location-aware).

Invariants (Slice 20):
  Company On Hand (Material.quantity_on_hand) == sum(InventoryBalance.quantity_on_hand)
  Available = On Hand - Reserved ;  Reservations NEVER change On Hand
  Transfer nets to zero company-wide; Receive/Return increase On Hand once; Issue/Waste/Damage/Loss decrease once.
Reservation ledger (reason=job_reservation) is unchanged from Job Automation and is location-agnostic.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from decimal import Decimal, ROUND_HALF_UP

from models import (Material, InventoryLocation, InventoryBalance, InventoryTxn, JobMaterial)

DISPOSITION = {"waste", "damage", "loss"}
Q4 = Decimal("0.0001")


def _r3(v):
    return round(float(v or 0), 3)


def _d(v):
    """Coerce to Decimal (or None). Quantities/costs enter Decimal math via str to avoid float drift."""
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q4(v):
    if v is None:
        return None
    return _d(v).quantize(Q4, rounding=ROUND_HALF_UP)


def record_receipt_cost(material: Material, qty, unit_cost):
    """Update the material's Moving Weighted Average Cost (MWAC) for a receipt of `qty` at `unit_cost`.
    MUST run BEFORE the receipt qty is added to on_hand (uses pre-receipt on_hand as the old weight).
    An unpriced receipt (unit_cost None or <= 0) introduces no cost basis and leaves MWAC untouched.
    Returns (unit_cost_dec, extended_cost_dec) for the ledger txn (both None when unpriced)."""
    uc = _d(unit_cost)
    if uc is None or uc <= 0:
        return (None, None)
    q = _d(qty)
    old_oh = _d(material.quantity_on_hand or 0)
    old_avg = _d(material.avg_cost)
    if old_avg is None or old_oh <= 0:
        new_avg = uc
    else:
        denom = old_oh + q
        new_avg = ((old_oh * old_avg) + (q * uc)) / denom if denom > 0 else uc
    material.avg_cost = _q4(new_avg)
    return (_q4(uc), _q4(q * uc))


def _consume_cost(material: Material, qty):
    """Cost of removing `qty` at the material's current MWAC (issue / waste / damage / loss).
    Returns (unit_cost_dec, extended_cost_dec) with extended_cost NEGATIVE (cost leaving inventory).
    (None, None) when the material has no established cost basis (surfaced as Missing Cost Basis)."""
    avg = _d(material.avg_cost)
    if avg is None:
        return (None, None)
    q = _d(qty)
    return (_q4(avg), _q4(-(q * avg)))


async def outstanding_issued_avg_cost(db: AsyncSession, material_id, job_id):
    """Weighted average unit cost of material currently issued-outstanding to a job
    (Σ issued cost − Σ returned cost) / (issued qty − returned qty). Used to reverse cost on returns
    without exact layer tracing. Returns Decimal or None (no traceable issued cost basis)."""
    rows = (await db.execute(select(InventoryTxn.reason, InventoryTxn.delta, InventoryTxn.extended_cost).where(
        InventoryTxn.material_id == material_id, InventoryTxn.job_id == job_id,
        InventoryTxn.reason.in_(("job_issue", "job_return"))))).all()
    net_qty = Decimal(0)
    net_cost = Decimal(0)
    saw_cost = False
    for reason, delta, ext in rows:
        qmag = abs(_d(delta) or Decimal(0))
        if reason == "job_issue":
            net_qty += qmag
            if ext is not None:
                net_cost += -_d(ext)  # issue ext is negative -> positive cost
                saw_cost = True
        else:  # job_return
            net_qty -= qmag
            if ext is not None:
                net_cost -= _d(ext)   # return ext is positive -> reduces outstanding cost
                saw_cost = True
    if net_qty > 0 and saw_cost:
        return _q4(net_cost / net_qty)
    return None


async def sync_default_balance(db: AsyncSession, material: Material):
    """Ensure sum(location balances) == material.quantity_on_hand by absorbing any difference
    into the default location. Keeps the company==Σlocations invariant for create/import/manual-adjust paths."""
    total = (await db.execute(select(func.coalesce(func.sum(InventoryBalance.quantity_on_hand), 0)).where(
        InventoryBalance.material_id == material.id))).scalar() or 0
    diff = _r3((material.quantity_on_hand or 0) - float(total))
    if abs(diff) < 1e-9:
        return
    loc = await default_location(db)
    if not loc:
        return
    b = await _balance(db, material.id, loc.id)
    b.quantity_on_hand = _r3(b.quantity_on_hand + diff)


async def default_location(db: AsyncSession) -> InventoryLocation:
    loc = (await db.execute(select(InventoryLocation).where(InventoryLocation.is_default.is_(True)))).scalars().first()
    if not loc:
        loc = (await db.execute(select(InventoryLocation).where(InventoryLocation.active.is_(True)).order_by(InventoryLocation.created_at))).scalars().first()
    return loc


async def _balance(db: AsyncSession, material_id, location_id) -> InventoryBalance:
    b = (await db.execute(select(InventoryBalance).where(
        InventoryBalance.material_id == material_id, InventoryBalance.location_id == location_id))).scalars().first()
    if not b:
        b = InventoryBalance(material_id=material_id, location_id=location_id, quantity_on_hand=0)
        db.add(b)
        await db.flush()
    return b


async def location_qty(db: AsyncSession, material_id, location_id) -> float:
    b = (await db.execute(select(InventoryBalance.quantity_on_hand).where(
        InventoryBalance.material_id == material_id, InventoryBalance.location_id == location_id))).scalar()
    return _r3(b or 0)


async def add_at_location(db: AsyncSession, material: Material, location_id, qty: float):
    """Increase location balance and company On Hand by qty (receive/return)."""
    b = await _balance(db, material.id, location_id)
    b.quantity_on_hand = _r3(b.quantity_on_hand + qty)
    material.quantity_on_hand = _r3((material.quantity_on_hand or 0) + qty)


async def remove_at_location(db: AsyncSession, material: Material, location_id, qty: float, *, allow_override=False):
    """Decrease location balance and company On Hand by qty (issue/waste/damage/loss)."""
    b = await _balance(db, material.id, location_id)
    if qty > b.quantity_on_hand + 1e-9 and not allow_override:
        raise HTTPException(status_code=400, detail=f"Insufficient stock at location ({b.quantity_on_hand} available)")
    b.quantity_on_hand = _r3(b.quantity_on_hand - qty)
    material.quantity_on_hand = _r3((material.quantity_on_hand or 0) - qty)


async def reserved_for_job(db: AsyncSession, material_id, job_id) -> float:
    v = (await db.execute(select(func.coalesce(func.sum(InventoryTxn.delta), 0)).where(
        InventoryTxn.material_id == material_id, InventoryTxn.job_id == job_id, InventoryTxn.reason == "job_reservation"))).scalar() or 0
    return abs(_r3(v))


async def transfer(db, material: Material, src_id, dst_id, qty: float, user_email, notes=None, allow_override=False):
    if str(src_id) == str(dst_id):
        raise HTTPException(status_code=400, detail="Source and destination must differ")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    src = await _balance(db, material.id, src_id)
    if qty > src.quantity_on_hand + 1e-9 and not allow_override:
        raise HTTPException(status_code=400, detail=f"Insufficient stock at source ({src.quantity_on_hand})")
    src.quantity_on_hand = _r3(src.quantity_on_hand - qty)
    dst = await _balance(db, material.id, dst_id)
    dst.quantity_on_hand = _r3(dst.quantity_on_hand + qty)
    # company total unchanged (net zero)
    db.add(InventoryTxn(material_id=material.id, delta=0, reason="transfer", source_location_id=src_id,
                        destination_location_id=dst_id, note=notes or f"Transfer {qty}", created_by=user_email))
    await db.flush()


async def issue(db, material: Material, location_id, qty: float, job_id, user_email, allow_override=False):
    """Issue to job: consume reservation first, reduce physical stock at location, increase Issued.
    Snapshots the current MWAC as the job cost basis (final — never revalued if MWAC later changes)."""
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    uc, ext = _consume_cost(material, qty)  # snapshot BEFORE removal (MWAC is unchanged by issuing)
    await remove_at_location(db, material, location_id, qty, allow_override=allow_override)
    # consume reservation (up to reserved) so Reserved drops and does not double-count
    if job_id:
        res = await reserved_for_job(db, material.id, job_id)
        consume = min(res, qty)
        if consume > 0:
            db.add(InventoryTxn(material_id=material.id, delta=_r3(consume), reason="job_reservation",
                                job_id=job_id, note="Reservation consumed by issue", created_by=user_email))
    db.add(InventoryTxn(material_id=material.id, delta=-_r3(qty), reason="job_issue", job_id=job_id,
                        source_location_id=location_id, unit_cost=uc, extended_cost=ext,
                        note="Issued to job", created_by=user_email))
    await db.flush()


async def return_to_stock(db, material: Material, location_id, qty: float, job_id, user_email, reason=None):
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    # Reverse cost using the weighted average of what is currently issued-outstanding to the job.
    basis = await outstanding_issued_avg_cost(db, material.id, job_id) if job_id else None
    if basis is None:
        basis = _d(material.avg_cost)  # fall back to current MWAC when no traceable issued cost
    q = _d(qty)
    # Returning material to inventory re-introduces cost basis -> fold back into MWAC (like a receipt).
    if basis is not None and basis > 0:
        old_oh = _d(material.quantity_on_hand or 0)
        old_avg = _d(material.avg_cost)
        if old_avg is None or old_oh <= 0:
            material.avg_cost = _q4(basis)
        else:
            material.avg_cost = _q4(((old_oh * old_avg) + (q * basis)) / (old_oh + q))
    await add_at_location(db, material, location_id, qty)
    uc = _q4(basis) if basis is not None else None
    ext = _q4(q * basis) if basis is not None else None
    db.add(InventoryTxn(material_id=material.id, delta=_r3(qty), reason="job_return", job_id=job_id,
                        destination_location_id=location_id, unit_cost=uc, extended_cost=ext,
                        note=reason or "Returned from job", created_by=user_email))
    await db.flush()


async def disposition(db, material: Material, location_id, qty: float, kind: str, user_email, job_id=None, reason=None, allow_override=False):
    if kind not in DISPOSITION:
        raise HTTPException(status_code=400, detail="kind must be waste, damage, or loss")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    uc, ext = _consume_cost(material, qty)  # cost tracked separately from productive issue
    await remove_at_location(db, material, location_id, qty, allow_override=allow_override)
    db.add(InventoryTxn(material_id=material.id, delta=-_r3(qty), reason=kind, job_id=job_id,
                        source_location_id=location_id, unit_cost=uc, extended_cost=ext,
                        note=reason or f"{kind}", created_by=user_email))
    await db.flush()


async def cycle_count_adjust(db, material: Material, location_id, counted: float, user_email, notes=None):
    b = await _balance(db, material.id, location_id)
    system = b.quantity_on_hand
    variance = _r3(counted - system)
    if abs(variance) < 1e-9:
        return {"variance": 0, "system": system, "counted": counted}
    b.quantity_on_hand = _r3(counted)
    material.quantity_on_hand = _r3((material.quantity_on_hand or 0) + variance)
    db.add(InventoryTxn(material_id=material.id, delta=variance, reason="cycle_count",
                        destination_location_id=location_id if variance > 0 else None,
                        source_location_id=location_id if variance < 0 else None,
                        note=notes or f"Cycle count: system {system} -> counted {counted}", created_by=user_email))
    await db.flush()
    return {"variance": variance, "system": system, "counted": counted}


async def auto_release_reservations(db, job, user_email) -> dict:
    """Release remaining (unissued) reservations for a job. Idempotent. Does not touch On Hand."""
    jms = (await db.execute(select(JobMaterial).where(JobMaterial.job_id == job.id))).scalars().all()
    released = 0.0
    for jm in jms:
        res = await reserved_for_job(db, jm.material_id, job.id)
        if res > 0:
            db.add(InventoryTxn(material_id=jm.material_id, delta=_r3(res), reason="job_reservation",
                                job_id=job.id, note="Auto-release on job close/cancel", created_by=user_email))
            released += res
    await db.flush()
    return {"released": _r3(released), "materials": len(jms)}


async def job_material_consumption(db, material_id, job_id) -> dict:
    async def _s(reason):
        v = (await db.execute(select(func.coalesce(func.sum(InventoryTxn.delta), 0)).where(
            InventoryTxn.material_id == material_id, InventoryTxn.job_id == job_id, InventoryTxn.reason == reason))).scalar() or 0
        return abs(_r3(v))
    issued = await _s("job_issue")
    returned = await _s("job_return")
    waste = _r3(sum([await _s("waste"), await _s("damage"), await _s("loss")]))
    return {"issued": issued, "returned": returned, "waste": waste, "net_used": _r3(issued - returned)}
