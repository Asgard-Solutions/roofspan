"""Server-authoritative access control for the mobile salesperson surface.

The mobile UI is NEVER trusted to enforce permissions. Every mobile route that returns or mutates a
record funnels through these helpers. A `sales` user may only reach records assigned/authorized to
them; management field roles (owner/administrator/office) retain broad access. Direct-object access
(changing a UUID in a URL) is blocked here, not in the client.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Lead, Job, Property, Inspection, Visit, CanvassSection, CanvassSectionProperty


def is_sales(user) -> bool:
    return getattr(user, "role", None) == "sales"


async def assert_lead_access(db: AsyncSession, lead: Lead, user) -> None:
    if is_sales(user) and lead.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="You no longer have access to this Lead.")


async def assert_job_access(db: AsyncSession, job: Job, user) -> None:
    if is_sales(user) and job.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="You no longer have access to this Job.")


async def property_accessible(db: AsyncSession, property_id, user) -> bool:
    """A salesperson may reach a Property only via (a) an active canvass section assigned to them,
    (b) a Lead assigned to them, or (c) a Job assigned to them."""
    if not is_sales(user):
        return True
    q_section = (
        select(CanvassSectionProperty.id)
        .join(CanvassSection, CanvassSection.id == CanvassSectionProperty.section_id)
        .where(
            CanvassSectionProperty.property_id == property_id,
            CanvassSection.assigned_user_id == user.id,
            CanvassSection.active.is_(True),
        )
        .limit(1)
    )
    if (await db.execute(q_section)).first():
        return True
    q_lead = select(Lead.id).where(Lead.property_id == property_id, Lead.assigned_user_id == user.id).limit(1)
    if (await db.execute(q_lead)).first():
        return True
    q_job = select(Job.id).where(Job.property_id == property_id, Job.assigned_user_id == user.id).limit(1)
    if (await db.execute(q_job)).first():
        return True
    return False


async def assert_property_access(db: AsyncSession, property_id, user) -> Property:
    p = await db.get(Property, property_id)
    if not p:
        raise HTTPException(status_code=404, detail="Property not found")
    if not await property_accessible(db, str(p.id), user):
        raise HTTPException(status_code=403, detail="You are not authorized to view this property.")
    return p


async def assert_inspection_access(db: AsyncSession, insp: Inspection, user) -> None:
    if not is_sales(user):
        return
    if insp.lead_id:
        lead = await db.get(Lead, insp.lead_id)
        if lead and lead.assigned_user_id == user.id:
            return
    if insp.property_id and await property_accessible(db, str(insp.property_id), user):
        return
    raise HTTPException(status_code=403, detail="You are not authorized to view this inspection.")


async def assert_record_access(db: AsyncSession, record_type: str, record_id: str, user) -> None:
    """Authorize a photo's parent record before upload/list/view. Sales get no access to
    office-only records (e.g. purchase_order)."""
    if not is_sales(user):
        return
    if record_type == "lead":
        rec = await db.get(Lead, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Lead not found")
        await assert_lead_access(db, rec, user)
    elif record_type == "job":
        rec = await db.get(Job, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Job not found")
        await assert_job_access(db, rec, user)
    elif record_type == "property":
        await assert_property_access(db, record_id, user)
    elif record_type == "inspection":
        rec = await db.get(Inspection, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Inspection not found")
        await assert_inspection_access(db, rec, user)
    elif record_type == "visit":
        rec = await db.get(Visit, record_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Visit not found")
        await assert_property_access(db, str(rec.property_id), user)
    elif record_type.startswith("measurement_"):
        from services import measurements as _meas
        rev, mset = await _meas.resolve_revision_for_photo(db, record_type, record_id)
        if not rev or not mset:
            raise HTTPException(status_code=404, detail="Measurement record not found")
        if mset.lead_id:
            lead = await db.get(Lead, mset.lead_id)
            if lead:
                await assert_lead_access(db, lead, user)
                return
        if mset.property_id:
            await assert_property_access(db, str(mset.property_id), user)
            return
        raise HTTPException(status_code=403, detail="You are not authorized for this measurement.")
    else:
        raise HTTPException(status_code=403, detail="You are not authorized for this record.")
