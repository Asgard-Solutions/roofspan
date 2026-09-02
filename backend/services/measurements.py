"""Roof Measurement service.

Owns whole-document create/replace with client-ref linkage, derived physical + takeoff-scoped totals,
the draft -> field_complete -> office_verified -> locked state machine, immutable revision cloning,
and measurement photo lineage. Estimating assumptions remain outside this service.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    MeasurementSet, MeasurementRevision, MeasurementStructure, MeasurementFacet,
    MeasurementEdge, MeasurementPenetration, MeasurementSummary, Photo,
)
from measurement_extension_models import MeasurementRevisionExtension
from services.measurement_core import derive_measurement_totals
from core import MANAGE_ROLES, FIELD_ROLES

VERIFY_ROLES = MANAGE_ROLES  # owner | administrator | office
STATUSES = ["draft", "field_complete", "office_verified", "locked"]


def _now():
    return datetime.now(timezone.utc)


def _parse_token_dt(value):
    """Normalize an optimistic-concurrency token (datetime or ISO string) to an aware-UTC datetime.
    Tolerant to the 'Z' suffix (Pydantic response) vs '+00:00' (isoformat) drift and naive datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def token_conflict(current, if_match) -> bool:
    """True when the caller's If-Match token does NOT match the current server token (a real conflict).
    An absent If-Match or absent server token is treated as no conflict (backward compatible)."""
    if not if_match or current is None:
        return False
    incoming = _parse_token_dt(if_match)
    cur = _parse_token_dt(current)
    if incoming is None or cur is None:
        # Unparseable — fall back to a raw string compare against the canonical isoformat.
        cur_s = current.isoformat() if hasattr(current, "isoformat") else str(current)
        return str(if_match) != cur_s
    return incoming != cur


def is_editable(rev: MeasurementRevision) -> bool:
    return (rev.status in ("draft", "field_complete")) and not rev.is_immutable


async def _extension(db: AsyncSession, revision_id) -> MeasurementRevisionExtension | None:
    return await db.get(MeasurementRevisionExtension, revision_id)


async def _save_extension(
    db: AsyncSession,
    revision_id,
    *,
    structure_scope: dict | None = None,
    existing_condition=None,
    drip_edge_lf=None,
) -> MeasurementRevisionExtension:
    row = await db.get(MeasurementRevisionExtension, revision_id)
    if row is None:
        row = MeasurementRevisionExtension(revision_id=revision_id)
        db.add(row)
    row.structure_scope = dict(structure_scope or {})
    row.existing_condition = existing_condition
    row.drip_edge_lf = drip_edge_lf
    row.updated_at = _now()
    await db.flush()
    return row


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


async def _insert_children(db: AsyncSession, rev: MeasurementRevision, payload) -> dict[str, dict[str, str]]:
    """Insert the whole measurement document and return client-ref -> server-id lineage maps."""
    struct_map: dict[str, str] = {}
    structure_scope: dict[str, bool] = {}
    for s in (payload.structures or []):
        row = MeasurementStructure(
            revision_id=rev.id, name=s.name or "", structure_type=s.structure_type or "main_house",
            stories=s.stories, approx_height_ft=s.approx_height_ft, attachment=s.attachment,
            notes=s.notes, sort=s.sort or 0,
        )
        db.add(row)
        await db.flush()
        structure_scope[str(row.id)] = bool(getattr(s, "included_in_scope", True))
        if s.ref:
            struct_map[str(s.ref)] = str(row.id)

    facet_map: dict[str, str] = {}
    for f in (payload.facets or []):
        sid = None
        if f.structure_ref and str(f.structure_ref) in struct_map:
            sid = struct_map[str(f.structure_ref)]
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
            facet_map[str(f.ref)] = str(row.id)

    def _fid(ref, fid):
        if ref and str(ref) in facet_map:
            return facet_map[str(ref)]
        return fid or None

    for e in (payload.edges or []):
        db.add(MeasurementEdge(
            revision_id=rev.id, edge_type=e.edge_type or "eave", length_ft=e.length_ft or 0,
            facet_id=_fid(e.facet_ref, e.facet_id), facet_id_secondary=_fid(e.facet_ref_secondary, e.facet_id_secondary),
            label=e.label, notes=e.notes, sort=e.sort or 0,
        ))

    penetration_map: dict[str, str] = {}
    for p in (payload.penetrations or []):
        row = MeasurementPenetration(
            revision_id=rev.id, pen_type=p.pen_type or "pipe_boot", quantity=p.quantity or 1,
            facet_id=_fid(p.facet_ref, p.facet_id), diameter_in=p.diameter_in, width_in=p.width_in,
            length_in=p.length_in, notes=p.notes, sort=p.sort or 0,
        )
        db.add(row)
        await db.flush()
        if getattr(p, "ref", None):
            penetration_map[str(p.ref)] = str(row.id)

    existing_condition = None
    drip_edge_lf = None
    if payload.summary is not None:
        summary_data = payload.summary.model_dump()
        existing_condition = summary_data.pop("existing_condition", None)
        drip_edge_lf = summary_data.pop("drip_edge_lf", None)
        db.add(MeasurementSummary(revision_id=rev.id, **summary_data))

    await db.flush()
    await _save_extension(
        db, rev.id, structure_scope=structure_scope,
        existing_condition=existing_condition, drip_edge_lf=drip_edge_lf,
    )
    return {
        "measurement_structure": struct_map,
        "measurement_facet": facet_map,
        "measurement_penetration": penetration_map,
    }


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


def _is_server_ref(val) -> bool:
    """A ref that is a real server UUID means the client is claiming an existing persisted row owned by
    this revision. Temporary client keys (e.g. 'r-abc123') are NOT UUIDs and always denote a NEW row."""
    if val is None:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _stale_reference():
    # Generic message on purpose: never disclose whether a foreign UUID exists elsewhere.
    raise HTTPException(
        status_code=409,
        detail="A referenced measurement item is stale or does not belong to this revision. Reload the worksheet and try again.",
    )


async def _reconcile_children(db: AsyncSession, rev: MeasurementRevision, payload) -> dict[str, list[str]]:
    """Identity-preserving reconciliation of an editable revision's children.

    A server-UUID `ref` claims an existing row owned by THIS revision -> UPDATE in place (its UUID is
    kept, so its roof sketch document and photos are untouched). A temporary/absent ref -> INSERT. An
    existing row omitted from the payload -> DELETE (intentional; sketch CASCADE fires by design). A
    UUID ref/id that does not belong to this revision is rejected (409) rather than silently reused or
    re-inserted. Returns the ids of children that were intentionally deleted (for photo retention)."""
    rid = rev.id

    # ---------------- structures ----------------
    existing_structs = {str(x.id): x for x in (await db.execute(select(MeasurementStructure).where(MeasurementStructure.revision_id == rid))).scalars().all()}
    struct_map: dict[str, str] = {}
    structure_scope: dict[str, bool] = {}
    seen_struct: set[str] = set()
    for s in (payload.structures or []):
        ref = s.ref
        row = None
        if _is_server_ref(ref):
            row = existing_structs.get(str(ref))
            if row is None:
                _stale_reference()
            seen_struct.add(str(row.id))
        if row is not None:
            row.name = s.name or ""
            row.structure_type = s.structure_type or "main_house"
            row.stories = s.stories
            row.approx_height_ft = s.approx_height_ft
            row.attachment = s.attachment
            row.notes = s.notes
            row.sort = s.sort or 0
        else:
            row = MeasurementStructure(
                revision_id=rid, name=s.name or "", structure_type=s.structure_type or "main_house",
                stories=s.stories, approx_height_ft=s.approx_height_ft, attachment=s.attachment,
                notes=s.notes, sort=s.sort or 0,
            )
            db.add(row)
            await db.flush()
        structure_scope[str(row.id)] = bool(getattr(s, "included_in_scope", True))
        if ref:
            struct_map[str(ref)] = str(row.id)
    final_struct_ids = set(structure_scope.keys())
    deleted_struct_ids = [sid for sid in existing_structs if sid not in seen_struct]
    for sid in deleted_struct_ids:
        await db.delete(existing_structs[sid])
    await db.flush()

    def _resolve_structure(f) -> str | None:
        if f.structure_ref and str(f.structure_ref) in struct_map:
            return struct_map[str(f.structure_ref)]
        if _is_server_ref(f.structure_ref):
            if str(f.structure_ref) in final_struct_ids:
                return str(f.structure_ref)
            _stale_reference()
        if f.structure_id:
            if str(f.structure_id) in final_struct_ids:
                return str(f.structure_id)
            _stale_reference()
        return None

    # ---------------- facets ----------------
    existing_facets = {str(x.id): x for x in (await db.execute(select(MeasurementFacet).where(MeasurementFacet.revision_id == rid))).scalars().all()}
    facet_map: dict[str, str] = {}
    seen_facet: set[str] = set()
    all_facet_ids: set[str] = set()
    for f in (payload.facets or []):
        sid = _resolve_structure(f)
        ref = f.ref
        row = None
        if _is_server_ref(ref):
            row = existing_facets.get(str(ref))
            if row is None:
                _stale_reference()
            seen_facet.add(str(row.id))
        if row is not None:
            row.structure_id = sid
            row.facet_label = f.facet_label or ""
            row.pitch_rise = f.pitch_rise
            row.area_sqft = f.area_sqft or 0
            row.width_ft = f.width_ft
            row.length_ft = f.length_ft
            row.orientation_azimuth = f.orientation_azimuth
            row.roof_material = f.roof_material
            row.notes = f.notes
            row.geometry = f.geometry
            row.sort = f.sort or 0
        else:
            row = MeasurementFacet(
                revision_id=rid, structure_id=sid, facet_label=f.facet_label or "",
                pitch_rise=f.pitch_rise, area_sqft=f.area_sqft or 0, width_ft=f.width_ft, length_ft=f.length_ft,
                orientation_azimuth=f.orientation_azimuth, roof_material=f.roof_material, notes=f.notes,
                geometry=f.geometry, sort=f.sort or 0,
            )
            db.add(row)
            await db.flush()
        all_facet_ids.add(str(row.id))
        if ref:
            facet_map[str(ref)] = str(row.id)
    deleted_facet_ids = [fid for fid in existing_facets if fid not in seen_facet]
    for fid in deleted_facet_ids:
        await db.delete(existing_facets[fid])
    await db.flush()

    def _fid(ref, fid) -> str | None:
        if ref and str(ref) in facet_map:
            return facet_map[str(ref)]
        if _is_server_ref(ref):
            if str(ref) in all_facet_ids:
                return str(ref)
            _stale_reference()
        if fid:
            if str(fid) in all_facet_ids:
                return str(fid)
            _stale_reference()
        return None

    # ---------------- edges ----------------
    existing_edges = {str(x.id): x for x in (await db.execute(select(MeasurementEdge).where(MeasurementEdge.revision_id == rid))).scalars().all()}
    seen_edge: set[str] = set()
    for e in (payload.edges or []):
        ref = getattr(e, "ref", None)
        row = None
        if _is_server_ref(ref):
            row = existing_edges.get(str(ref))
            if row is None:
                _stale_reference()
            seen_edge.add(str(row.id))
        primary = _fid(e.facet_ref, e.facet_id)
        secondary = _fid(e.facet_ref_secondary, e.facet_id_secondary)
        if row is not None:
            row.edge_type = e.edge_type or "eave"
            row.length_ft = e.length_ft or 0
            row.facet_id = primary
            row.facet_id_secondary = secondary
            row.label = e.label
            row.notes = e.notes
            row.sort = e.sort or 0
        else:
            db.add(MeasurementEdge(
                revision_id=rid, edge_type=e.edge_type or "eave", length_ft=e.length_ft or 0,
                facet_id=primary, facet_id_secondary=secondary, label=e.label, notes=e.notes, sort=e.sort or 0,
            ))
    deleted_edge_ids = [eid for eid in existing_edges if eid not in seen_edge]
    for eid in deleted_edge_ids:
        await db.delete(existing_edges[eid])
    await db.flush()

    # ---------------- penetrations ----------------
    existing_pens = {str(x.id): x for x in (await db.execute(select(MeasurementPenetration).where(MeasurementPenetration.revision_id == rid))).scalars().all()}
    seen_pen: set[str] = set()
    for p in (payload.penetrations or []):
        ref = p.ref
        row = None
        if _is_server_ref(ref):
            row = existing_pens.get(str(ref))
            if row is None:
                _stale_reference()
            seen_pen.add(str(row.id))
        fid = _fid(p.facet_ref, p.facet_id)
        if row is not None:
            row.pen_type = p.pen_type or "pipe_boot"
            row.quantity = p.quantity or 1
            row.facet_id = fid
            row.diameter_in = p.diameter_in
            row.width_in = p.width_in
            row.length_in = p.length_in
            row.notes = p.notes
            row.sort = p.sort or 0
        else:
            db.add(MeasurementPenetration(
                revision_id=rid, pen_type=p.pen_type or "pipe_boot", quantity=p.quantity or 1,
                facet_id=fid, diameter_in=p.diameter_in, width_in=p.width_in,
                length_in=p.length_in, notes=p.notes, sort=p.sort or 0,
            ))
    deleted_pen_ids = [pid for pid in existing_pens if pid not in seen_pen]
    for pid in deleted_pen_ids:
        await db.delete(existing_pens[pid])
    await db.flush()

    # ---------------- summary (singleton per revision, no ref) ----------------
    existing_summary = (await db.execute(select(MeasurementSummary).where(MeasurementSummary.revision_id == rid))).scalars().first()
    existing_condition = None
    drip_edge_lf = None
    if payload.summary is not None:
        summary_data = payload.summary.model_dump()
        existing_condition = summary_data.pop("existing_condition", None)
        drip_edge_lf = summary_data.pop("drip_edge_lf", None)
        if existing_summary is not None:
            for k, v in summary_data.items():
                setattr(existing_summary, k, v)
        else:
            db.add(MeasurementSummary(revision_id=rid, **summary_data))
    elif existing_summary is not None:
        await db.delete(existing_summary)
    await db.flush()

    # Extension structure_scope tracks EXACTLY the final structures; deleted ids drop out naturally.
    await _save_extension(
        db, rev.id, structure_scope=structure_scope,
        existing_condition=existing_condition, drip_edge_lf=drip_edge_lf,
    )

    return {
        "measurement_structure": deleted_struct_ids,
        "measurement_facet": deleted_facet_ids,
        "measurement_penetration": deleted_pen_ids,
    }


async def replace_children(db: AsyncSession, rev: MeasurementRevision, payload) -> None:
    """Identity-preserving editable-revision save. Surviving children keep their UUIDs (so their roof
    sketch documents and photos are untouched); only intentionally removed children are deleted."""
    if not is_editable(rev):
        raise HTTPException(status_code=409, detail="This revision is verified/locked and cannot be edited. Create a new revision instead.")
    deleted_ids_by_type = await _reconcile_children(db, rev, payload)
    if payload.source:
        rev.source = payload.source
    rev.provider = payload.provider
    rev.report_id = payload.report_id
    rev.reported_area_sqft = payload.reported_area_sqft
    rev.notes = payload.notes
    await _retain_deleted_child_photos(db, str(rev.id), deleted_ids_by_type)
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
    ext = await _extension(db, rev.id)
    old_scope = (ext.structure_scope or {}) if ext else {}

    smap: dict[str, str] = {}
    fmap: dict[str, str] = {}
    pmap: dict[str, str] = {}
    for s in structs:
        r = MeasurementStructure(
            revision_id=new.id, name=s.name, structure_type=s.structure_type, stories=s.stories,
            approx_height_ft=s.approx_height_ft, attachment=s.attachment, notes=s.notes, sort=s.sort,
        )
        db.add(r)
        await db.flush()
        smap[str(s.id)] = r.id
    for f in facets:
        r = MeasurementFacet(
            revision_id=new.id, structure_id=smap.get(str(f.structure_id)) if f.structure_id else None,
            facet_label=f.facet_label, pitch_rise=f.pitch_rise, area_sqft=f.area_sqft, width_ft=f.width_ft,
            length_ft=f.length_ft, orientation_azimuth=f.orientation_azimuth, roof_material=f.roof_material,
            notes=f.notes, geometry=f.geometry, sort=f.sort,
        )
        db.add(r)
        await db.flush()
        fmap[str(f.id)] = r.id
    emap: dict[str, str] = {}
    for e in edges:
        r = MeasurementEdge(
            revision_id=new.id, edge_type=e.edge_type, length_ft=e.length_ft,
            facet_id=fmap.get(str(e.facet_id)) if e.facet_id else None,
            facet_id_secondary=fmap.get(str(e.facet_id_secondary)) if e.facet_id_secondary else None,
            label=e.label, notes=e.notes, sort=e.sort,
        )
        db.add(r)
        await db.flush()
        emap[str(e.id)] = str(r.id)
    for p in pens:
        r = MeasurementPenetration(
            revision_id=new.id, pen_type=p.pen_type, quantity=p.quantity,
            facet_id=fmap.get(str(p.facet_id)) if p.facet_id else None,
            diameter_in=p.diameter_in, width_in=p.width_in, length_in=p.length_in,
            notes=p.notes, sort=p.sort,
        )
        db.add(r)
        await db.flush()
        pmap[str(p.id)] = r.id
    if summ:
        cols = {c.name: getattr(summ, c.name) for c in MeasurementSummary.__table__.columns if c.name not in ("id", "revision_id")}
        db.add(MeasurementSummary(revision_id=new.id, **cols))
    await db.flush()

    new_scope = {str(new_id): bool(old_scope.get(str(old_id), True)) for old_id, new_id in smap.items()}
    await _save_extension(
        db, new.id, structure_scope=new_scope,
        existing_condition=ext.existing_condition if ext else None,
        drip_edge_lf=ext.drip_edge_lf if ext else None,
    )

    # Preserve photo attachments across the clone (new DB rows reuse the same stored object_path).
    id_remap = {("measurement_revision", str(rev.id)): str(new.id)}
    for old, nw in smap.items():
        id_remap[("measurement_structure", old)] = str(nw)
    for old, nw in fmap.items():
        id_remap[("measurement_facet", old)] = str(nw)
    for old, nw in pmap.items():
        id_remap[("measurement_penetration", old)] = str(nw)
    await _copy_photos(db, id_remap)
    # Copy roof sketch documents onto the clone, remapping to the new structure ids.
    from services import measurement_sketches as _sketch_svc
    await _sketch_svc.clone_sketches(
        db, rev.id, new.id,
        {str(o): str(nw) for o, nw in smap.items()},
        {str(o): str(nw) for o, nw in fmap.items()},
        {str(o): str(nw) for o, nw in pmap.items()},
        {str(o): str(nw) for o, nw in emap.items()},
    )
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
        rev.status = "field_complete"
        rev.field_complete_by = email
        rev.field_complete_at = _now()
    elif to == "office_verified":
        if cur not in ("field_complete", "draft"):
            raise HTTPException(status_code=409, detail=f"Cannot verify from '{cur}'")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can Office Verify")
        rev.status = "office_verified"
        rev.verified_by = email
        rev.verified_at = _now()
    elif to == "locked":
        if cur != "office_verified":
            raise HTTPException(status_code=409, detail="Only an Office Verified revision can be locked")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can lock")
        rev.status = "locked"
        rev.locked_by = email
        rev.locked_at = _now()
        rev.is_immutable = True
    elif to == "draft":
        if cur not in ("field_complete", "office_verified"):
            raise HTTPException(status_code=409, detail=f"Cannot return to Draft from '{cur}'")
        if not _has_role(user, VERIFY_ROLES):
            raise HTTPException(status_code=403, detail="Only Office/Owner/Admin can return a measurement to the field")
        rev.status = "draft"
        rev.verified_by = None
        rev.verified_at = None
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
    ext = await _extension(db, rev.id)
    scope = (ext.structure_scope or {}) if ext else {}

    structure_out = [{
        "id": str(x.id), "name": x.name, "structure_type": x.structure_type,
        "included_in_scope": bool(scope.get(str(x.id), True)),
        "stories": x.stories, "approx_height_ft": x.approx_height_ft,
        "attachment": x.attachment, "notes": x.notes, "sort": x.sort,
    } for x in structs]
    facet_out = [{
        "id": str(f.id), "structure_id": str(f.structure_id) if f.structure_id else None,
        "facet_label": f.facet_label, "pitch_rise": f.pitch_rise, "area_sqft": f.area_sqft,
        "width_ft": f.width_ft, "length_ft": f.length_ft, "orientation_azimuth": f.orientation_azimuth,
        "roof_material": f.roof_material, "notes": f.notes, "geometry": f.geometry, "sort": f.sort,
    } for f in facets]
    edge_out = [{
        "id": str(e.id), "edge_type": e.edge_type, "length_ft": e.length_ft,
        "facet_id": str(e.facet_id) if e.facet_id else None,
        "facet_id_secondary": str(e.facet_id_secondary) if e.facet_id_secondary else None,
        "label": e.label, "notes": e.notes, "sort": e.sort,
    } for e in edges]
    penetration_out = [{
        "id": str(p.id), "pen_type": p.pen_type, "quantity": p.quantity,
        "facet_id": str(p.facet_id) if p.facet_id else None, "diameter_in": p.diameter_in,
        "width_in": p.width_in, "length_in": p.length_in, "notes": p.notes, "sort": p.sort,
    } for p in pens]

    totals = derive_measurement_totals(structure_out, facet_out, edge_out, penetration_out)
    reported = rev.reported_area_sqft
    totals["reported_area_sqft"] = reported
    totals["reported_area_delta_sqft"] = round(totals["total_area_sqft"] - reported, 2) if reported is not None else None

    summary_out = None
    if summ:
        summary_out = {c.name: getattr(summ, c.name) for c in MeasurementSummary.__table__.columns if c.name not in ("id", "revision_id")}
    elif ext and (ext.existing_condition is not None or ext.drip_edge_lf is not None):
        summary_out = {}
    if summary_out is not None:
        summary_out["existing_condition"] = ext.existing_condition if ext else None
        summary_out["drip_edge_lf"] = ext.drip_edge_lf if ext else None

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
        "structures": structure_out,
        "facets": facet_out,
        "edges": edge_out,
        "penetrations": penetration_out,
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


# ---------------- measurement photos ----------------
PHOTO_RECORD_TYPES = ("measurement_revision", "measurement_structure", "measurement_facet", "measurement_penetration")


async def resolve_revision_for_photo(db: AsyncSession, record_type: str, record_id: str):
    """Return (revision, set) for a measurement photo parent, or (None, None)."""
    if record_type not in PHOTO_RECORD_TYPES:
        return None, None
    rev = None
    if record_type == "measurement_revision":
        rev = await db.get(MeasurementRevision, record_id)
    elif record_type == "measurement_structure":
        row = await db.get(MeasurementStructure, record_id)
        rev = await db.get(MeasurementRevision, row.revision_id) if row else None
    elif record_type == "measurement_facet":
        row = await db.get(MeasurementFacet, record_id)
        rev = await db.get(MeasurementRevision, row.revision_id) if row else None
    elif record_type == "measurement_penetration":
        row = await db.get(MeasurementPenetration, record_id)
        rev = await db.get(MeasurementRevision, row.revision_id) if row else None
    if not rev:
        return None, None
    s = await db.get(MeasurementSet, rev.set_id)
    return rev, s


async def _retain_deleted_child_photos(db: AsyncSession, revision_id: str, deleted_ids_by_type: dict) -> None:
    """When a child is intentionally removed during an editable save, its photos are retained on the
    measurement revision so field/office evidence is never silently orphaned. Surviving children keep
    their UUIDs, so their photos require NO relinking at all (never moved unnecessarily)."""
    for record_type, ids in (deleted_ids_by_type or {}).items():
        for old_id in ids or []:
            rows = (await db.execute(select(Photo).where(Photo.record_type == record_type, Photo.record_id == str(old_id)))).scalars().all()
            for photo in rows:
                photo.record_type = "measurement_revision"
                photo.record_id = str(revision_id)
    await db.flush()


async def _copy_photos(db: AsyncSession, id_remap: dict) -> None:
    """Duplicate Photo rows onto cloned measurement records while reusing stored object paths."""
    from datetime import datetime, timezone as _tz
    for (rtype, old_id), new_id in id_remap.items():
        rows = (await db.execute(select(Photo).where(Photo.record_type == rtype, Photo.record_id == str(old_id)))).scalars().all()
        for p in rows:
            db.add(Photo(
                object_path=p.object_path, content_type=p.content_type, record_type=rtype,
                record_id=str(new_id), description=p.description, category=p.category,
                uploaded_by=p.uploaded_by, created_at=datetime.now(_tz.utc),
            ))
    await db.flush()


async def revision_photo_records(db: AsyncSession, rev: MeasurementRevision) -> list[str]:
    """All stable record_ids that can carry a photo for this revision."""
    ids = [str(rev.id)]
    for model in (MeasurementStructure, MeasurementFacet, MeasurementPenetration):
        rows = (await db.execute(select(model.id).where(model.revision_id == rev.id))).scalars().all()
        ids.extend(str(x) for x in rows)
    return ids
