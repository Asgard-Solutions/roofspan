"""Operational Reports (release-ready, K.I.S.S.). A single summary derived from existing RoofSpan
data — sales pipeline, jobs, inventory, and (for finance-authorized roles) invoice revenue. Not a BI
tool: no report designer, custom SQL, or data warehouse.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, Lead, Job, Invoice, Material
from core import get_current_user, MANAGE_ROLES

router = APIRouter(prefix="/api/reports", tags=["reports"])

_OPEN_LEAD_STATUSES = ("new", "working", "qualified")


@router.get("/summary")
async def reports_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Sales pipeline
    lead_rows = (await db.execute(select(Lead.status, func.count()).group_by(Lead.status))).all()
    leads_by_status = {s: c for s, c in lead_rows}
    pipeline = {
        "by_status": leads_by_status,
        "total_leads": sum(leads_by_status.values()),
        "active_leads": sum(c for s, c in leads_by_status.items() if s in _OPEN_LEAD_STATUSES),
        "converted_leads": leads_by_status.get("converted", 0),
    }

    # Jobs
    job_rows = (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    jobs_by_status = {s: c for s, c in job_rows}
    jobs = {"by_status": jobs_by_status, "total_jobs": sum(jobs_by_status.values())}

    # Inventory low-stock (threshold must be set; qty at/below it)
    low = (await db.execute(
        select(Material).where(
            Material.active == True,  # noqa: E712
            Material.reorder_threshold > 0,
            Material.quantity_on_hand <= Material.reorder_threshold,
        ).order_by(Material.quantity_on_hand.asc())
    )).scalars().all()
    low_stock = [
        {"id": str(m.id), "name": m.name, "unit": m.unit,
         "quantity_on_hand": m.quantity_on_hand, "reorder_threshold": m.reorder_threshold}
        for m in low
    ]
    inventory = {"low_stock_count": len(low_stock), "low_stock": low_stock[:20]}

    result = {"pipeline": pipeline, "jobs": jobs, "inventory": inventory}

    # Finance is sensitive: only finance-authorized roles (owner/administrator/office) see revenue.
    if user.role in MANAGE_ROLES:
        inv_rows = (await db.execute(
            select(Invoice.status, func.count(), func.coalesce(func.sum(Invoice.total), 0.0)).group_by(Invoice.status)
        )).all()
        by_status = {}
        total_invoiced = paid = outstanding = 0.0
        for s, c, tot in inv_rows:
            tot = float(tot or 0)
            by_status[s] = {"count": c, "total": tot}
            total_invoiced += tot
            if s == "paid":
                paid += tot
            elif s == "issued":
                outstanding += tot
        result["finance"] = {
            "by_status": by_status,
            "total_invoiced": total_invoiced,
            "paid": paid,
            "outstanding": outstanding,
        }

    return result
