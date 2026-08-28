"""Roof Measurement service (Increment A).

Owns: whole-document create/replace with client-ref linkage, derived totals, the status state machine
(draft -> field_complete -> office_verified -> locked, plus return-to-field), immutability, and
cloning a verified/locked revision into a new editable draft. No estimating logic lives here.
"""
from datetime import datetime, timezone
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models import (
    MeasurementSet, MeasurementRevision, MeasurementStructure, MeasurementFacet,
    MeasurementEdge, MeasurementPenetration, MeasurementSummary,
)
from core import MANAGE_ROLES, FIELD_ROLES

VERIFY_ROLES = MANAGE_ROLES  # owner | administrator | office

STATUSES = ["draft", "field_complete", "office_verified", "locked"]
EDGE_KEYS = ["eave", "rake", "ridge", "hip", "valley", "sidewall", "headwall", "transition"]


def _now():
    return datetime.now(timezone.utc)


def is_editable(rev: MeasurementRevision) -> bool:
    return (rev.status in ("draft", "field_complete")) and not rev.is_immutable


# ---------------- set / revision creation ----------------
async def get_or_create_set(db: AsyncSession, *, inspection_id=None, property_id=None, lead_id=None, created_by=None) -> MeasurementSet:
    stmt = select(MeasurementSet)
    if inspection_id:
        stmt = stmt.where(MeasurementSet.inspection_id == inspection_id)
    elif property_id:
        stmt = stmt.where(MeasurementSet.property_id == property_id)
    elif lead_id:
        stmt = stmt.where(MeasurementSet.lead_id == lead_id)
    else:
        raise HTTPException(status_code=400, detail="A measurement needs an inspection_id, property_id or lead_id")
    existing = (await db.execute(stmt.order_by(MeasurementSet.created_at.asc()))).scalars().first()
    if existing:
        return existing
    s = MeasurementSet(inspection_id=inspection_id, property_id=property_id, lead_id=lead_id, created_by=created_by)
    db.add(s)
    await db.flush()
    return s


async def _next_revision_number(db: AsyncSession, set_id) -> int:
    n = (await db.execute(select(func.max(MeasurementRevision.revision_number)).where(MeasurementRevision.set_id == set_id))).scalar()
    return int(n or 0) + 1


async def _insert_children(db: AsyncSession, rev: MeasurementRevision, payload) -> None:
    """Insert structures/facets/edges/penetrations/summary, resolving client refs to new UUIDs."""
    struct_map: dict[str, str] = {}
    for s in (payload.structures or []):
        row = MeasurementStructure(
            revision_id=rev.id, name=s.name or "", structure_type=s.structure_type or "main_house",
            stories=s.stories, approx_height_ft=s.approx_height_ft, attachment=s.attachment,
            notes=s.notes, sort=s.sort or 0,
        )
        db.add(row)
        await db.flush()
        if s.ref:
            struct_map[s.ref] = str(row.id)

    facet_map: dict[str, str] = {}
    for f in (payload.facets or []):
        sid = None
        if f.structure_ref and f.structure_ref in struct_map:
            sid = struct_map[f.structure_ref]
        elif f.structure_id:
            sid = f.structure_id
        row = MeasurementFacet(
            revision_id=rev.id, structure_id=sid, facet_label=f.facet_label or "",
            pitch_rise=f.pitch_rise, area_sqft=f.area_sqft or 0, width_ft=f.width_ft, length_ft=f.length_ft,
            orientation_azimuth=f.orientation_azimuth, roof_material=f.roof_material, notes=f.notes,
            geometry=f.geometry, sort=f.sort or 0,
        )
        db.add(row)
        await db.flush()
        if f.ref:
            facet_map[f.ref] = str(row.id)

    def _fid(ref, fid):
        if ref and ref in facet_map:
            return facet_map[ref]
        return fid or None

    for e in (payload.edges or []):
        db.add(MeasurementEdge(
            revision_id=rev.id, edge_type=e.edge_type or "eave", length_ft=e.length_ft or 0,
            facet_id=_fid(e.facet_ref, e.facet_id), facet_id_secondary=_fid(e.facet_ref_secondary, e.facet_id_secondary),
            label=e.label, notes=e.notes, sort=e.sort or 0,
        ))
    for p in (payload.penetrations or []):
        db.add(MeasurementPenetration(
            revision_id=rev.id, pen_type=p.pen_type or "pipe_boot", quantity=p.quantity or 1,
            facet_id=_fid(p.facet_ref, p.facet_id), diameter_in=p.diameter_in, width_in=p.width_in,
            length_in=p.length_in, notes=p.notes, sort=p.sort or 0,
        ))
    if payload.summary is not None:
        db.add(MeasurementSummary(revision_id=rev.id, **payload.summary.model_dump()))
    await db.flush()


async def create_revision(db: AsyncSession, payload, user) -> MeasurementRevision:
    s = await get_or_create_set(
        db, inspection_id=payload.inspection_id, property_id=payload.property_id,
        lead_id=payload.lead_id, created_by=getattr(user, "email", None),
    )
    rev = MeasurementRevision(
        set_id=s.id, revision_number=await _next_revision_number(db, s.id), status="draft",
        source=payload.source or "field", provider=payload.provider, report_id=payload.report_id,
        reported_area_sqft=payload.reported_area_sqft, notes=payload.notes,
        created_by=getattr(user, "email", None),
    )
    if payload.source == "imported":
        rev.imported_at = _now()
    db.add(rev)
    await db.flush()
    await _insert_children(db, rev, payload)
    if payload.mark_field_complete:
        rev.status = "field_complete"
        rev.field_complete_by = getattr(user, "email", None)
        rev.field_complete_at = _now()
    return rev


async def replace_children(db: AsyncSession, rev: MeasurementRevision, payload) -> None:
    """Replace a DRAFT/field-complete revision's contents wholesale (matches offline whole-document sync)."""
    if not is_editable(rev):
        raise HTTPException(status_code=409, detail="This revision is verified/locked and cannot be edited. Create a new revision instead.")
    for model in (MeasurementEdge, MeasurementPenetration, MeasurementFacet, MeasurementStructure):
        await db.execute(delete(model).where(model.revision_id == rev.id))
    await db.execute(delete(MeasurementSummary).where(MeasurementSummary.revision_id == rev.id))
    await db.flush()
    # metadata that may change on a draft edit
    if payload.source:
        rev.source = payload.source
    rev.provider = payload.provider
    rev.report_id = payload.report_id
    rev.reported_area_sqft = payload.reported_area_sqft
    rev.notes = payload.notes
    await _insert_children(db, rev, payload)
    rev.updated_at = _now()


async def clone_revision(db: AsyncSession, rev: MeasurementRevision, user) -> MeasurementRevision:
    """Deep-copy a revision into a new editable draft that supersedes it (audit-safe history)."""
    new = MeasurementRevision(
        set_id=rev.set_id, revision_number=await _next_revision_number(db, rev.set_id), status="draft",
        supersedes_revision_id=rev.id, source="office", provider=rev.provider, report_id=rev.report_id,
        reported_area_sqft=rev.reported_area_sqft, notes=rev.notes, created_by=getattr(user, "email", None),
    )
    db.add(new)
    await db.flush()
    structs = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id))).scalars().all()
    facets = (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == rev.id))).scalars().all()
    edges = (await db.execute(select(MeasurementEdge).where(MeasurementEdge.revision_id == rev.id))).scalars().all()
    pens = (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == rev.id))).scalars().all()
    summ = (await db.execute(select(MeasurementSummary).where(MeasurementSummary.revision_id == rev.id))).scalars().first()
    smap: dict[str, str] = {}
    for s in structs:
        r = MeasurementStructure(revision_id=new.id, name=s.name, structure_type=s.structure_type, stories=s.stories,
                                 approx_height_ft=s.approx_height_ft, attachment=s.attachment, notes=s.notes, sort=s.sort)
        db.add(r); await db.flush(); smap[str(s.id)] = r.id
    fmap: dict[str, str] = {}
    for f in facets:
        r = MeasurementFacet(revision_id=new.id, structure_id=smap.get(str(f.structure_id)) if f.structure_id else None,
                             facet_label=f.facet_label, pitch_rise=f.pitch_rise, area_sqft=f.area_sqft, width_ft=f.width_ft,
                             length_ft=f.length_ft, orientation_azimuth=f.orientation_azimuth, roof_material=f.roof_material,
                             notes=f.notes, geometry=f.geometry, sort=f.sort)
        db.add(r); await db.flush(); fmap[str(f.id)] = r.id
    for e in edges:
        db.add(MeasurementEdge(revision_id=new.id, edge_type=e.edge_type, length_ft=e.length_ft,
                               facet_id=fmap.get(str(e.facet_id)) if e.facet_id else None,
                               facet_id_secondary=fmap.get(str(e.facet_id_secondary)) if e.facet_id_secondary else None,
                               label=e.label, notes=e.notes, sort=e.sort))
    for p in pens:
        db.add(MeasurementPenetration(revision_id=new.id, pen_type=p.pen_type, quantity=p.quantity,
                                      facet_id=fmap.get(str(p.facet_id)) if p.facet_id else None,
                                      diameter_in=p.diameter_in, width_in=p.width_in, length_in=p.length_in,
                                      notes=p.notes, sort=p.sort))
    if summ:
        cols = {c.name: getattr(summ, c.name) for c in MeasurementSummary.__table__.columns if c.name not in ("id", "revision_id")}
        db.add(MeasurementSummary(revision_id=new.id, **cols))
    await db.flush()
    return new


# ---------------- status state machine ----------------
def _has_role(user, roles) -> bool:
    return getattr(user, "role", None) in roles


async def transition_status(db: AsyncSession, rev: MeasurementRevision, to: str, user) -> MeasurementRevision:
    if to not in STATUSES:
        raise HTTPException(status_code=400, detail=f"Unknown status '{to}'")
    if rev.is_immutable:
        raise HTTPException(status_code=409, detail="This revision is immutable (locked or referenced by an accepted quote/job).")
    cur = rev.status
    email = getattr(user, "email", None)

    if to == "field_complete":
        if cur not in ("draft", "field_complete"):
            raise HTTPException(status_code=409, detail=f"Cannot mark Field Complete from '{cur}'")
        if not _has_role(user, FIELD_ROLES):
            raise HTTPException(status_code=403, detail="Not permitted to mark Field Complete")
        rev.status = "field_complete"; rev.field_complete_by = email; rev.field_complete_at = _now()
    elif to == "office_verified":
        if cur not in ("field_complete", "draft"):
            raise HTTPException(status_code=409, detail=f"Cannot verify from '{cur}'")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can Office Verify")
        rev.status = "office_verified"; rev.verified_by = email; rev.verified_at = _now()
    elif to == "locked":
        if cur != "office_verified":
            raise HTTPException(status_code=409, detail="Only an Office Verified revision can be locked")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can lock")
        rev.status = "locked"; rev.locked_by = email; rev.locked_at = _now(); rev.is_immutable = True
    elif to == "draft":  # return to field
        if cur not in ("field_complete", "office_verified"):
            raise HTTPException(status_code=409, detail=f"Cannot return to Draft from '{cur}'")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can return a measurement to the field")
        rev.status = "draft"; rev.verified_by = None; rev.verified_at = None
    rev.updated_at = _now()
    return rev


# ---------------- derived totals + serialization ----------------
async def build_out(db: AsyncSession, rev: MeasurementRevision) -> dict:
    s = await db.get(MeasurementSet, rev.set_id)
    structs = (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rev.id).order_by(MeasurementStructure.sort))).scalars().all()
    facets = (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == rev.id).order_by(MeasurementFacet.sort))).scalars().all()
    edges = (await db.execute(select(MeasurementEdge).where(MeasurementEdge.revision_id == rev.id).order_by(MeasurementEdge.sort))).scalars().all()
    pens = (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == rev.id).order_by(MeasurementPenetration.sort))).scalars().all()
    summ = (await db.execute(select(MeasurementSummary).where(MeasurementSummary.revision_id == rev.id))).scalars().first()

    total_area = round(sum(f.area_sqft or 0 for f in facets), 2)
    # area by pitch
    pitch_areas: dict = {}
    for f in facets:
        key = f.pitch_rise
        pitch_areas[key] = pitch_areas.get(key, 0) + (f.area_sqft or 0)
    area_by_pitch = [
        {"pitch": k, "area_sqft": round(v, 2), "squares": round(v / 100, 2)}
        for k, v in sorted(pitch_areas.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    ]
    predominant_pitch = None
    if pitch_areas:
        predominant_pitch = max(pitch_areas.items(), key=lambda kv: kv[1])[0]
    # area by structure
    sname = {str(x.id): x.name or x.structure_type for x in structs}
    struct_areas: dict = {}
    for f in facets:
        key = str(f.structure_id) if f.structure_id else None
        struct_areas[key] = struct_areas.get(key, 0) + (f.area_sqft or 0)
    area_by_structure = [
        {"structure_id": k, "name": sname.get(k, "Unassigned") if k else "Unassigned",
         "area_sqft": round(v, 2), "squares": round(v / 100, 2)}
        for k, v in struct_areas.items()
    ]
    # edge totals
    edge_totals = {f"{k}_lf": 0.0 for k in EDGE_KEYS}
    for e in edges:
        key = f"{e.edge_type}_lf"
        if key in edge_totals:
            edge_totals[key] += (e.length_ft or 0)
    edge_totals = {k: round(v, 2) for k, v in edge_totals.items()}
    # penetration counts
    pen_counts: dict = {}
    pen_total = 0
    for p in pens:
        pen_counts[p.pen_type] = pen_counts.get(p.pen_type, 0) + (p.quantity or 0)
        pen_total += (p.quantity or 0)

    reported = rev.reported_area_sqft
    delta = round(total_area - reported, 2) if reported is not None else None

    totals = {
        "total_area_sqft": total_area,
        "total_squares": round(total_area / 100, 2),
        "facet_count": len(facets),
        "structure_count": len(structs),
        "predominant_pitch": predominant_pitch,
        "area_by_pitch": area_by_pitch,
        "area_by_structure": area_by_structure,
        "edge_totals": edge_totals,
        "penetration_counts": pen_counts,
        "penetration_total": pen_total,
        "reported_area_sqft": reported,
        "reported_area_delta_sqft": delta,
    }

    summary_out = None
    if summ:
        summary_out = {c.name: getattr(summ, c.name) for c in MeasurementSummary.__table__.columns if c.name not in ("id", "revision_id")}

    return {
        "id": str(rev.id), "set_id": str(rev.set_id), "revision_number": rev.revision_number,
        "status": rev.status, "supersedes_revision_id": str(rev.supersedes_revision_id) if rev.supersedes_revision_id else None,
        "is_immutable": rev.is_immutable, "editable": is_editable(rev), "source": rev.source,
        "provider": rev.provider, "report_id": rev.report_id, "imported_at": rev.imported_at,
        "reported_area_sqft": rev.reported_area_sqft, "notes": rev.notes,
        "inspection_id": str(s.inspection_id) if s and s.inspection_id else None,
        "property_id": str(s.property_id) if s and s.property_id else None,
        "lead_id": str(s.lead_id) if s and s.lead_id else None,
        "created_by": rev.created_by, "created_at": rev.created_at, "updated_at": rev.updated_at,
        "field_complete_by": rev.field_complete_by, "field_complete_at": rev.field_complete_at,
        "verified_by": rev.verified_by, "verified_at": rev.verified_at,
        "locked_by": rev.locked_by, "locked_at": rev.locked_at,
        "structures": [{
            "id": str(x.id), "name": x.name, "structure_type": x.structure_type, "stories": x.stories,
            "approx_height_ft": x.approx_height_ft, "attachment": x.attachment, "notes": x.notes, "sort": x.sort,
        } for x in structs],
        "facets": [{
            "id": str(f.id), "structure_id": str(f.structure_id) if f.structure_id else None,
            "facet_label": f.facet_label, "pitch_rise": f.pitch_rise, "area_sqft": f.area_sqft,
            "width_ft": f.width_ft, "length_ft": f.length_ft, "orientation_azimuth": f.orientation_azimuth,
            "roof_material": f.roof_material, "notes": f.notes, "geometry": f.geometry, "sort": f.sort,
        } for f in facets],
        "edges": [{
            "id": str(e.id), "edge_type": e.edge_type, "length_ft": e.length_ft,
            "facet_id": str(e.facet_id) if e.facet_id else None,
            "facet_id_secondary": str(e.facet_id_secondary) if e.facet_id_secondary else None,
            "label": e.label, "notes": e.notes, "sort": e.sort,
        } for e in edges],
        "penetrations": [{
            "id": str(p.id), "pen_type": p.pen_type, "quantity": p.quantity,
            "facet_id": str(p.facet_id) if p.facet_id else None, "diameter_in": p.diameter_in,
            "width_in": p.width_in, "length_in": p.length_in, "notes": p.notes, "sort": p.sort,
        } for p in pens],
        "summary": summary_out,
        "totals": totals,
    }


async def list_revisions_for_set(db: AsyncSession, set_id) -> list[dict]:
    revs = (await db.execute(select(MeasurementRevision).where(MeasurementRevision.set_id == set_id).order_by(MeasurementRevision.revision_number.desc()))).scalars().all()
    out = []
    for rev in revs:
        area = (await db.execute(select(func.coalesce(func.sum(MeasurementFacet.area_sqft), 0)).where(MeasurementFacet.revision_id == rev.id))).scalar() or 0
        out.append({
            "id": str(rev.id), "set_id": str(rev.set_id), "revision_number": rev.revision_number,
            "status": rev.status, "source": rev.source, "is_immutable": rev.is_immutable,
            "total_area_sqft": round(area, 2), "total_squares": round(area / 100, 2),
            "created_by": rev.created_by, "created_at": rev.created_at, "verified_at": rev.verified_at,
            "supersedes_revision_id": str(rev.supersedes_revision_id) if rev.supersedes_revision_id else None,
        })
    return out
