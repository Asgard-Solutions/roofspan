from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import Job, User
from core import get_current_user
from schemas_phase3 import JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _out(j: Job) -> JobOut:
    return JobOut(id=str(j.id), number=j.number, quote_id=str(j.quote_id) if j.quote_id else None,
                  customer_id=str(j.customer_id) if j.customer_id else None,
                  property_id=str(j.property_id) if j.property_id else None,
                  status=j.status, scope=j.scope, total=j.total, created_at=j.created_at)


@router.get("", response_model=list[JobOut])
async def list_jobs(customer_id: str | None = Query(None), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Job).order_by(Job.created_at.desc())
    if customer_id:
        stmt = stmt.where(Job.customer_id == customer_id)
    return [_out(j) for j in (await db.execute(stmt)).scalars().all()]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    j = await db.get(Job, job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return _out(j)
