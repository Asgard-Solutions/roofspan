"""Versioned roof sketch service (Plan 1 Task 2).

Rules:
- One document per (revision_id, structure_id).
- Structure-level optimistic concurrency via document_version; stale writes raise SketchConflict.
- Verified/locked (immutable) revisions cannot be mutated.
- Never mutates relational measurement values.
- clone_sketches() copies documents onto a cloned revision, remapping structure ids.
"""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from measurement_sketch_models import MeasurementSketchDocument
from models import MeasurementRevision, MeasurementStructure
from services.measurements import is_editable

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
    existing = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == revision_id,
        MeasurementSketchDocument.structure_id == structure_id))).scalars().first()

    if existing is None:
        if expected_version not in (None, 0):
            raise SketchConflict({"document_version": 0, "document": {}, "exists": False})
        row = MeasurementSketchDocument(
            revision_id=revision_id, structure_id=structure_id, schema_version=schema_version or 1,
            document_version=1, edit_mode=edit_mode or "connected_graph", document=document or {},
            created_by=email, updated_by=email,
        )
        db.add(row)
        await db.flush()
        return _out(row)

    if expected_version is None or int(expected_version) != int(existing.document_version):
        raise SketchConflict(_out(existing))

    existing.document = document or {}
    existing.edit_mode = edit_mode or existing.edit_mode
    existing.schema_version = schema_version or existing.schema_version
    existing.document_version = int(existing.document_version) + 1
    existing.updated_by = email
    existing.updated_at = _now()
    await db.flush()
    return _out(existing)


async def clone_sketches(db: AsyncSession, from_revision_id, to_revision_id, structure_id_map: dict) -> int:
    """Copy sketch docs onto a cloned revision, remapping to the new structure ids. Fresh version=1."""
    rows = (await db.execute(select(MeasurementSketchDocument).where(
        MeasurementSketchDocument.revision_id == from_revision_id))).scalars().all()
    copied = 0
    for r in rows:
        new_struct = structure_id_map.get(str(r.structure_id))
        if not new_struct:
            continue
        db.add(MeasurementSketchDocument(
            revision_id=to_revision_id, structure_id=new_struct, schema_version=r.schema_version,
            document_version=1, edit_mode=r.edit_mode, document=r.document or {},
            created_by=r.created_by, updated_by=r.updated_by,
        ))
        copied += 1
    await db.flush()
    return copied
