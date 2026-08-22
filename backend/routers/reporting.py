"""Cost & profitability reporting (Actual Job Costing). All endpoints expose internal cost/margin
data and are therefore gated to owner/administrator/office — the Sales role is never granted access."""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import csv
import io
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import require_roles, MANAGE_ROLES
from services import job_costing as jc

router = APIRouter(prefix="/api/reports/costing", tags=["reports-costing"])


def _csv_response(filename: str, headers: list[str], rows: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    for r in rows:
        w.writerow(r)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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


# ---- CSV exports (same authorized data as the reports; Sales blocked server-side) ----
@router.get("/profitability.csv")
async def profitability_csv(status: str | None = Query(None), user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    d = await jc.profitability_report(db, status=status)
    rows = [[r["job_number"], r["job_status"], r["costing_status"], r["revenue"], r["estimated_cost"],
             r["actual_cost"], r["actual_gross_profit"], r["actual_gross_margin_percent"], r["total_variance"]]
            for r in d["rows"]]
    return _csv_response("job_profitability.csv",
                         ["Job", "Status", "Costing Status", "Revenue", "Estimated Cost", "Actual Cost",
                          "Actual Gross Profit", "Actual Margin %", "Total Variance"], rows)


@router.get("/cost-variance.csv")
async def cost_variance_csv(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    d = await jc.profitability_report(db)
    rows = [[r["job_number"], r["estimated_cost"], r["actual_cost"], r["total_variance"]] for r in d["rows"]]
    return _csv_response("job_cost_variance.csv", ["Job", "Estimated Cost", "Actual Cost", "Variance"], rows)


@router.get("/material-variance.csv")
async def material_variance_csv(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    d = await jc.material_variance_report(db)
    rows = [[r["material_name"], r["estimated_cost"], r["actual_cost"], r["variance"], r["waste_cost"],
             r["issued_quantity"], r["waste_quantity"], "yes" if r["missing_cost_basis"] else "no"] for r in d["rows"]]
    return _csv_response("material_variance.csv",
                         ["Material", "Estimated Cost", "Actual Cost", "Variance", "Waste Cost",
                          "Issued Qty", "Waste Qty", "Missing Cost Basis"], rows)


@router.get("/waste.csv")
async def waste_csv(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    d = await jc.waste_cost_report(db)
    rows = [[r["material_name"], r["waste_quantity"], r["waste_cost"]] for r in d["rows"]]
    return _csv_response("waste_cost.csv", ["Material", "Waste Qty", "Waste Cost"], rows)


@router.get("/supplier-impact.csv")
async def supplier_impact_csv(user: User = Depends(require_roles(*MANAGE_ROLES)), db: AsyncSession = Depends(get_db)):
    d = await jc.supplier_cost_impact_report(db)
    rows = [[r["supplier_name"], r["po_count"], r["received_cost"]] for r in d["rows"]]
    return _csv_response("supplier_cost_impact.csv", ["Supplier", "POs Received", "Received Cost"], rows)
