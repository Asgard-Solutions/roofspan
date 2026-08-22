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

from models import (Material, InventoryLocation, InventoryBalance, InventoryTxn, JobMaterial)

DISPOSITION = {"waste", "damage", "loss"}


def _r3(v):
    return round(float(v or 0), 3)


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
    """Issue to job: consume reservation first, reduce physical stock at location, increase Issued."""
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    await remove_at_location(db, material, location_id, qty, allow_override=allow_override)
    # consume reservation (up to reserved) so Reserved drops and does not double-count
    if job_id:
        res = await reserved_for_job(db, material.id, job_id)
        consume = min(res, qty)
        if consume > 0:
            db.add(InventoryTxn(material_id=material.id, delta=_r3(consume), reason="job_reservation",
                                job_id=job_id, note="Reservation consumed by issue", created_by=user_email))
    db.add(InventoryTxn(material_id=material.id, delta=-_r3(qty), reason="job_issue", job_id=job_id,
                        source_location_id=location_id, note="Issued to job", created_by=user_email))
    await db.flush()


async def return_to_stock(db, material: Material, location_id, qty: float, job_id, user_email, reason=None):
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    await add_at_location(db, material, location_id, qty)
    db.add(InventoryTxn(material_id=material.id, delta=_r3(qty), reason="job_return", job_id=job_id,
                        destination_location_id=location_id, note=reason or "Returned from job", created_by=user_email))
    await db.flush()


async def disposition(db, material: Material, location_id, qty: float, kind: str, user_email, job_id=None, reason=None, allow_override=False):
    if kind not in DISPOSITION:
        raise HTTPException(status_code=400, detail="kind must be waste, damage, or loss")
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    await remove_at_location(db, material, location_id, qty, allow_override=allow_override)
    db.add(InventoryTxn(material_id=material.id, delta=-_r3(qty), reason=kind, job_id=job_id,
                        source_location_id=location_id, note=reason or f"{kind}", created_by=user_email))
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
