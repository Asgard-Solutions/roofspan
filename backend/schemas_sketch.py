"""Pydantic envelopes for roof sketch read/write."""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel


class SketchWriteIn(BaseModel):
    schema_version: int = 1
    edit_mode: str = "connected_graph"
    document: Dict[str, Any] = {}
    expected_version: Optional[int] = None   # optimistic token; None allowed for first create


class SketchOut(BaseModel):
    id: str
    revision_id: str
    structure_id: str
    schema_version: int
    document_version: int
    edit_mode: str
    document: Dict[str, Any]
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
