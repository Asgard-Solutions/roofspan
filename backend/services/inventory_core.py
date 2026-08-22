"""Inventory Core 2.0 — supplier-material + inventory-quantity services (shared by routers)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Supplier, SupplierMaterial, Material, InventoryTxn, JobMaterial, POLineItem, PurchaseOrder, Job

# ... (module continues)
_ACTIVE_JOB_STATUSES_EXCLUDED = ("completed", "cancelled", "closed", "archived", "lost")

# Ledger transaction types (structured). delta sign convention: positive increases On Hand.
TXN_TYPES = [
    "initial_inventory", "receive_po", "job_reservation", "job_issue", "job_return",
    "supplier_return", "transfer", "damage", "waste", "loss", "cycle_count", "manual_correction",
    "adjustment",  # legacy generic type retained for backward compatibility
]
# PO statuses that count toward On Order (not yet fully received, not cancelled).
_OPEN_PO_STATUSES = ("draft", "ready_for_review", "submitted", "ordered", "confirmed", "acknowledged", "scheduled", "partially_received", "picking", "shipped")


async def ensure_supplier(db: AsyncSession, name: str, integration_provider: str | None = None) -> Supplier:
    sup = (await db.execute(select(Supplier).where(Supplier.name == name))).scalars().first()
    if not sup:
        sup = Supplier(name=name, integration_provider=integration_provider, active=True)
        db.add(sup)
        await db.flush()
    elif integration_provider and not sup.integration_provider:
        sup.integration_provider = integration_provider
    return sup


async def upsert_supplier_material(db: AsyncSession, *, material_id, supplier_id, integration_provider,
                                   external_item_id=None, supplier_item_number=None, supplier_description=None,
                                   supplier_uom=None, current_cost=None, availability_status=None,
                                   meta=None, make_preferred_if_first=True) -> SupplierMaterial:
    """Create or update a supplier↔material mapping. If it's the material's first mapping and
    make_preferred_if_first is set, mark it preferred."""
    q = select(SupplierMaterial).where(SupplierMaterial.material_id == material_id,
                                       SupplierMaterial.integration_provider == integration_provider)
    if supplier_id is not None:
        q = q.where(SupplierMaterial.supplier_id == supplier_id)
    if external_item_id is not None:
        q = q.where(SupplierMaterial.external_item_id == external_item_id)
    sm = (await db.execute(q)).scalars().first()
    existing_count = (await db.execute(select(func.count(SupplierMaterial.id)).where(SupplierMaterial.material_id == material_id))).scalar() or 0
    if not sm:
        sm = SupplierMaterial(material_id=material_id, supplier_id=supplier_id, integration_provider=integration_provider,
                              is_preferred=(existing_count == 0 and make_preferred_if_first))
        db.add(sm)
    sm.supplier_id = supplier_id
    if external_item_id is not None:
        sm.external_item_id = external_item_id
    if supplier_item_number is not None:
        sm.supplier_item_number = supplier_item_number
    if supplier_description is not None:
        sm.supplier_description = supplier_description
    if supplier_uom is not None:
        sm.supplier_uom = supplier_uom
    if current_cost is not None:
        sm.current_cost = current_cost
        sm.price_status = "priced"
        sm.price_updated_at = datetime.now(timezone.utc)
    if availability_status is not None:
        sm.availability_status = availability_status
        sm.availability_updated_at = datetime.now(timezone.utc)
    if meta is not None:
        sm.meta = meta
    return sm


async def set_preferred_supplier(db: AsyncSession, material_id, supplier_material_id) -> SupplierMaterial:
    """Mark one mapping preferred; clear preferred on all other active mappings for the material.
    Clears others FIRST and flushes, then sets the chosen one — so the DB partial-unique index
    (one active preferred per material) is never transiently violated."""
    rows = (await db.execute(select(SupplierMaterial).where(SupplierMaterial.material_id == material_id))).scalars().all()
    chosen = next((r for r in rows if str(r.id) == str(supplier_material_id)), None)
    if not chosen:
        return None
    for r in rows:
        if r is not chosen and r.is_preferred:
            r.is_preferred = False
    await db.flush()
    chosen.is_preferred = True
    await db.flush()
    return chosen


# ---------------- Inventory quantity calculations ----------------
async def compute_quantities(db: AsyncSession, material: Material) -> dict:
    """Operational quantities. Supplier branch availability is NEVER used here — On Hand is physical.

    Reserved  = sum of job_reservation ledger deltas (stored negative → we sum their magnitudes)
    Required  = sum of JobMaterial.planned_quantity across active (non-completed/cancelled) jobs
    On Order  = sum of max(quantity - received_quantity, 0) over open PO lines for this material
    Available = On Hand - Reserved
    Projected = On Hand + On Order - Required
    """
    on_hand = float(material.quantity_on_hand or 0)

    reserved_row = (await db.execute(
        select(func.coalesce(func.sum(InventoryTxn.delta), 0)).where(
            InventoryTxn.material_id == material.id, InventoryTxn.reason == "job_reservation")
    )).scalar() or 0
    reserved = abs(float(reserved_row))

    # Required from ACTIVE job plans (exclude completed/cancelled/closed/archived/lost jobs)
    required = float((await db.execute(
        select(func.coalesce(func.sum(JobMaterial.planned_quantity), 0))
        .select_from(JobMaterial).join(Job, Job.id == JobMaterial.job_id)
        .where(JobMaterial.material_id == material.id, Job.status.notin_(_ACTIVE_JOB_STATUSES_EXCLUDED))
    )).scalar() or 0)

    on_order = float((await db.execute(
        select(func.coalesce(func.sum(func.greatest(POLineItem.quantity - POLineItem.received_quantity, 0)), 0))
        .select_from(POLineItem).join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(POLineItem.material_id == material.id, PurchaseOrder.status.in_(_OPEN_PO_STATUSES))
    )).scalar() or 0)

    available = round(on_hand - reserved, 3)
    projected = round(on_hand + on_order - required, 3)
    return {"on_hand": round(on_hand, 3), "reserved": round(reserved, 3), "available": available,
            "on_order": round(on_order, 3), "required": round(required, 3), "projected": projected}


async def best_known_cost(db: AsyncSession, material_id) -> float | None:
    val = (await db.execute(
        select(func.min(SupplierMaterial.current_cost)).where(
            SupplierMaterial.material_id == material_id, SupplierMaterial.active.is_(True),
            SupplierMaterial.current_cost.isnot(None))
    )).scalar()
    return float(val) if val is not None else None


async def best_known_supplier_material(db: AsyncSession, material_id) -> SupplierMaterial | None:
    """The active supplier mapping with the lowest known cost (labeled separately from preferred)."""
    return (await db.execute(
        select(SupplierMaterial).where(
            SupplierMaterial.material_id == material_id, SupplierMaterial.active.is_(True),
            SupplierMaterial.current_cost.isnot(None))
        .order_by(SupplierMaterial.current_cost.asc()).limit(1)
    )).scalars().first()


async def supplier_material_count(db: AsyncSession, material_id) -> int:
    return int((await db.execute(
        select(func.count()).select_from(SupplierMaterial).where(
            SupplierMaterial.material_id == material_id, SupplierMaterial.active.is_(True))
    )).scalar() or 0)


async def preferred_supplier_material(db: AsyncSession, material_id) -> SupplierMaterial | None:
    return (await db.execute(
        select(SupplierMaterial).where(SupplierMaterial.material_id == material_id,
                                       SupplierMaterial.is_preferred.is_(True),
                                       SupplierMaterial.active.is_(True))
    )).scalars().first()
