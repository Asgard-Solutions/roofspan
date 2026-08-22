"""Cost & profitability reporting (Actual Job Costing). All endpoints expose internal cost/margin
data and are therefore gated to owner/administrator/office — the Sales role is never granted access."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import require_roles, MANAGE_ROLES
from services import job_costing as jc

router = APIRouter(prefix="/api/reports/costing", tags=["reports-costing"])


@router.get("/profitability")
async def profitability(status: str | None = Query(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    return await jc.profitability_report(db, status=status)


@router.get("/material-variance")
async def material_variance(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    return await jc.material_variance_report(db)


@router.get("/waste")
async def waste(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    return await jc.waste_cost_report(db)


@router.get("/supplier-impact")
async def supplier_impact(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    return await jc.supplier_cost_impact_report(db)
