"""Versioned roof sketch service (Plan 1 Task 2).

Rules:
- One document per (revision_id, structure_id).
- Structure-level optimistic concurrency via document_version; stale writes raise SketchConflict.
- Verified/locked (immutable) revisions cannot be mutated.
- Never mutates relational measurement values.
- clone_sketches() copies documents onto a cloned revision, remapping structure ids.
"""
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from measurement_sketch_models import MeasurementSketchDocument
from models import MeasurementRevision, MeasurementStructure
from services.measurements import is_editable

SUPPORTED_SCHEMA_VERSIONS = (1,)
SUPPORTED_EDIT_MODES = ("connected_graph", "manual_polygon")


def _normalize_document(document: dict, *, structure_id: str, edit_mode: str, schema_version: int) -> dict:
    """Reconcile the embedded JSON with the authoritative route/DB fields so the canonical sketch is
    never ambiguous. The route/DB structure id always wins; unsupported modes/versions are rejected."""
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported sketch schema_version {schema_version}")
    if edit_mode not in SUPPORTED_EDIT_MODES:
        raise HTTPException(status_code=422, detail=f"Unsupported sketch edit_mode '{edit_mode}'")
    doc = dict(document or {})
    embedded_struct = doc.get("structure_id")
    if embedded_struct is not None and str(embedded_struct) != str(structure_id):
        raise HTTPException(status_code=422, detail="Sketch document structure_id does not match the route structure")
    embedded_mode = doc.get("edit_mode")
    if embedded_mode is not None and embedded_mode != edit_mode:
        raise HTTPException(status_code=422, detail="Sketch document edit_mode contradicts the requested edit_mode")
    embedded_schema = doc.get("schema_version")
    if embedded_schema is not None and int(embedded_schema) != int(schema_version):
        raise HTTPException(status_code=422, detail="Sketch document schema_version contradicts the request")
    # authoritative fields win
    doc["structure_id"] = str(structure_id)
    doc["edit_mode"] = edit_mode
    doc["schema_version"] = int(schema_version)
    return doc

try:
    from roof_sketch_core import normalize_sketch_document  # optional python mirror (not required)
except Exception:  # geometry lives in JS; backend only stores/normalizes shape defensively
    normalize_sketch_document = None


class SketchConflict(Exception):
    def __init__(self, server: dict):
        self.server = server
        super().__init__("sketch version conflict")


def _now():
    return datetime.now(timezone.utc)


def _out(doc: MeasurementSketchDocument) -> dict:
    return {
        "id": str(doc.id), "revision_id": str(doc.revision_id), "structure_id": str(doc.structure_id),
        "schema_version": doc.schema_version, "document_version": doc.document_version,
        "edit_mode": doc.edit_mode, "document": doc.document or {},
        "created_by": doc.created_by, "updated_by": doc.updated_by,
        "created_at": doc.created_at, "updated_at": doc.updated_at,
    }


async def _revision(db: AsyncSession, revision_id: str) -> MeasurementRevision:
    rev = await db.get(MeasurementRevision, revision_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    return rev


async def get_sketch(db: AsyncSession, revision_id: str, structure_id: str) -> dict | None:
    row = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == revision_id,
        MeasurementSketchDocument.structure_id == structure_id))).scalars().first()
    return _out(row) if row else None


async def list_sketches(db: AsyncSession, revision_id: str) -> list[dict]:
    rows = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == revision_id))).scalars().all()
    return [_out(r) for r in rows]


async def save_sketch(db: AsyncSession, revision_id: str, structure_id: str, *, edit_mode: str,
                      document: dict, schema_version: int, expected_version, user) -> dict:
    rev = await _revision(db, revision_id)
    if not is_editable(rev):
        raise HTTPException(status_code=409, detail="This measurement revision is locked. Create a new revision to edit its sketch.")
    structure = await db.get(MeasurementStructure, structure_id)
    if not structure or str(structure.revision_id) != str(revision_id):
        raise HTTPException(status_code=404, detail="Structure does not belong to this revision")

    email = getattr(user, "email", None)
    doc = _normalize_document(document, structure_id=str(structure_id), edit_mode=edit_mode or "connected_graph", schema_version=schema_version or 1)
    existing = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == revision_id,
        MeasurementSketchDocument.structure_id == structure_id))).scalars().first()

    if existing is None:
        if expected_version not in (None, 0):
            raise SketchConflict({"document_version": 0, "document": {}, "exists": False})
        row = MeasurementSketchDocument(
            revision_id=revision_id, structure_id=structure_id, schema_version=doc["schema_version"],
            document_version=1, edit_mode=doc["edit_mode"], document=doc,
            created_by=email, updated_by=email,
        )
        db.add(row)
        await db.flush()
        return _out(row)

    if expected_version is None:
        raise SketchConflict(_out(existing))

    # Atomic compare-and-swap: only update if the row is still at expected_version. Concurrent writers
    # block on the row lock; the loser matches 0 rows and gets a conflict (never last-write-wins).
    stmt = (
        update(MeasurementSketchDocument)
        .where(MeasurementSketchDocument.id == existing.id,
               MeasurementSketchDocument.document_version == int(expected_version))
        .values(document=doc, edit_mode=doc["edit_mode"], schema_version=doc["schema_version"],
                document_version=MeasurementSketchDocument.document_version + 1,
                updated_by=email, updated_at=_now())
        .returning(MeasurementSketchDocument.id)
    )
    res = await db.execute(stmt)
    if res.first() is None:
        # stale token: reload the authoritative current sketch for conflict review
        current = (await db.execute(select(MeasurementSketchDocument).where(
            MeasurementSketchDocument.id == existing.id))).scalars().first()
        raise SketchConflict(_out(current) if current else _out(existing))
    await db.flush()
    fresh = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.id == existing.id))).scalars().first()
    return _out(fresh)


def _remap_sketch_document(doc: dict, structure_map: dict, facet_map: dict, penetration_map: dict) -> dict:
    """Remap revision-scoped RELATIONAL ids embedded in a sketch when cloning to a new revision.
    Sketch graph ids (vertices/edges/facets *within* the drawing) are stable client ids and are left
    untouched; only references that point at relational DB records are remapped."""
    if not isinstance(doc, dict):
        return {}
    d = dict(doc)
    if d.get("structure_id") is not None:
        d["structure_id"] = structure_map.get(str(d["structure_id"]), d["structure_id"])
    rel = {"facet": facet_map, "penetration": penetration_map, "structure": structure_map}

    def remap_ref(obj):
        if isinstance(obj, dict):
            o = dict(obj)
            # proposal decisions & any node carrying a relational target reference
            tt = o.get("target_type")
            if tt in rel and o.get("target_id") is not None:
                o["target_id"] = rel[tt].get(str(o["target_id"]), o["target_id"])
            for k in ("measurement_facet_id", "relational_facet_id"):
                if o.get(k) is not None:
                    o[k] = facet_map.get(str(o[k]), o[k])
            for k in ("measurement_penetration_id", "relational_penetration_id"):
                if o.get(k) is not None:
                    o[k] = penetration_map.get(str(o[k]), o[k])
            return {k: remap_ref(v) for k, v in o.items()}
        if isinstance(obj, list):
            return [remap_ref(x) for x in obj]
        return obj

    return remap_ref(d)


async def clone_sketches(db: AsyncSession, from_revision_id, to_revision_id, structure_id_map: dict,
                         facet_id_map: dict = None, penetration_id_map: dict = None) -> int:
    """Copy sketch docs onto a cloned revision, remapping to new structure ids and remapping any
    embedded relational references. Fresh version=1."""
    facet_id_map = facet_id_map or {}
    penetration_id_map = penetration_id_map or {}
    rows = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == from_revision_id))).scalars().all()
    copied = 0
    for r in rows:
        new_struct = structure_id_map.get(str(r.structure_id))
        if not new_struct:
            continue
        new_doc = _remap_sketch_document(r.document or {}, structure_id_map, facet_id_map, penetration_id_map)
        new_doc["structure_id"] = str(new_struct)  # authoritative
        db.add(MeasurementSketchDocument(
            revision_id=to_revision_id, structure_id=new_struct, schema_version=r.schema_version,
            document_version=1, edit_mode=r.edit_mode, document=new_doc,
            created_by=r.created_by, updated_by=r.updated_by,
        ))
        copied += 1
    await db.flush()
    return copied
