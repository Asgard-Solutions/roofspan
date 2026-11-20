"""Ready to install = start date set + crew assigned + no material shortage (shared job_planning rule)."""
from sqlalchemy import select

from models import Crew
from services import job_planning as jp

CLOSED = ("completed", "cancelled")


def readiness(job, shortage: float) -> dict:
    if job.status in CLOSED:
        return {"ready": None, "reasons": []}
    reasons = []
    if not job.scheduled_start:
        reasons.append({"code": "schedule", "label": "Schedule the job"})
    if not job.crew_id:
        reasons.append({"code": "crew", "label": "Assign a crew"})
    if shortage > 0:
        reasons.append({"code": "materials", "label": "Materials are short"})
    return {"ready": not reasons, "reasons": reasons}


async def readiness_by_job(db, jobs) -> dict:
    short = await jp.shortages_by_job(db, [j.id for j in jobs])
    return {j.id: readiness(j, short.get(j.id, 0)) for j in jobs}


async def crew_name_map(db, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {c.id: c.name for c in (await db.execute(select(Crew).where(Crew.id.in_(ids)))).scalars().all()}
