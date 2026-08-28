from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class TakeoffRuleIn(BaseModel):
    name: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    quantity_factor: float = 1.0
    apply_waste: bool = False
    assembly_id: str
    assembly_waste_percent: Optional[float] = None
    coverage_per_package: Optional[float] = None


class TakeoffTemplateIn(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    active: bool = True
    default_waste_percent: float = 10.0
    notes: Optional[str] = None
    rules: List[TakeoffRuleIn] = []


class TakeoffTemplateRevisionIn(BaseModel):
    default_waste_percent: float = 10.0
    notes: Optional[str] = None
    rules: List[TakeoffRuleIn] = []


class TakeoffApplyIn(BaseModel):
    measurement_revision_id: str
    template_revision_id: str
    estimate_waste_override: Optional[float] = None
    structure_waste_overrides: Dict[str, float] = {}
    drip_edge_override_lf: Optional[float] = None
    replace_modified_generated: bool = False


class TakeoffPreviewOut(BaseModel):
    estimate_id: str
    measurement_revision_id: str
    measurement_revision_number: int
    template_revision_id: str
    template_revision_number: int
    company_default_waste_percent: float
    template_waste_percent: float
    effective_roof_waste_percent: float
    lines: List[dict] = []
    generated_line_ids_to_replace: List[str] = []
    manually_modified_generated_lines: List[dict] = []
    review_required: bool = False


class TakeoffStatusOut(BaseModel):
    estimate_id: str
    has_takeoff: bool = False
    takeoff_id: Optional[str] = None
    measurement_revision_id: Optional[str] = None
    measurement_revision_number: Optional[int] = None
    template_revision_id: Optional[str] = None
    template_revision_number: Optional[int] = None
    latest_measurement_revision_id: Optional[str] = None
    latest_measurement_revision_number: Optional[int] = None
    measurements_changed: bool = False
    changed_metrics: List[dict] = []
