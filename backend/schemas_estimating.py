from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ---- Assemblies ----
class AssemblyItemIn(BaseModel):
    id: Optional[str] = None
    material_id: Optional[str] = None
    description: str = ""
    quantity_factor: float = 1
    unit: str = "ea"
    waste_override: Optional[float] = None
    is_labor: bool = False


class AssemblyItemOut(AssemblyItemIn):
    id: str
    material_name: Optional[str] = None
    current_cost: Optional[float] = None
    sort: int = 0


class AssemblyIn(BaseModel):
    name: str = Field(min_length=1)
    category: Optional[str] = None
    unit_basis: str = "SQ"
    active: bool = True
    notes: Optional[str] = None
    items: List[AssemblyItemIn] = []


class AssemblyOut(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    unit_basis: str
    active: bool
    notes: Optional[str] = None
    version: int
    created_at: datetime
    items: List[AssemblyItemOut] = []


class AssemblyExpandOut(BaseModel):
    assembly_id: str
    assembly_name: str
    assembly_version: int
    unit_basis: str
    quantity: float
    lines: List[dict] = []


# ---- Price Books ----
class PriceBookEntryIn(BaseModel):
    id: Optional[str] = None
    target_type: str = "material"     # material | labor | assembly
    material_id: Optional[str] = None
    assembly_id: Optional[str] = None
    label: Optional[str] = None
    rule_type: str = "markup"         # fixed | markup | margin
    fixed_price: Optional[float] = None
    markup_percent: Optional[float] = None
    margin_percent: Optional[float] = None
    active: bool = True


class PriceBookEntryOut(PriceBookEntryIn):
    id: str
    material_name: Optional[str] = None
    assembly_name: Optional[str] = None
    sort: int = 0


class PriceBookIn(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    active: bool = True
    is_default: bool = False


class PriceBookPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    is_default: Optional[bool] = None


class PriceBookOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    active: bool
    is_default: bool
    created_at: datetime
    entries: List[PriceBookEntryOut] = []


# ---- Cost Refresh ----
class CostRefreshRow(BaseModel):
    line_id: str
    description: str
    material_id: Optional[str] = None
    supplier_name: Optional[str] = None
    old_cost: Optional[float] = None
    current_cost: Optional[float] = None
    delta: Optional[float] = None
    changed: bool = False
    cost_source: Optional[str] = None


class CostRefreshPreviewOut(BaseModel):
    estimate_id: str
    rows: List[CostRefreshRow] = []
    changed_count: int = 0


class CostRefreshApplyIn(BaseModel):
    line_ids: List[str] = []          # which lines to apply new cost to
    recalc_selling_price: bool = False  # if true, recompute sell from markup; else keep sell price
