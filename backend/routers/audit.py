from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import AuditLog, User
from core import require_roles, SENSITIVE_ROLES
from schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=dict)
async def list_audit(
    action: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_roles(*SENSITIVE_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one()

    items = [
        AuditOut(
            id=str(r.id), timestamp=r.timestamp, user_email=r.user_email, action=r.action,
            entity_type=r.entity_type, entity_id=r.entity_id, detail=r.detail, ip_address=r.ip_address,
        )
        for r in rows
    ]
    return {"items": [i.model_dump() for i in items], "total": total, "limit": limit, "offset": offset}
