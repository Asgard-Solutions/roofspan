"""DEV-ONLY licensing tooling. Mounted only when LICENSING_MODE == "dev".

Lets an Owner simulate Control-Plane subscription states (ACTIVE/GRACE/SUSPENDED/CANCELLED) and seat
counts so the state machine, guard middleware, and seat enforcement can be tested end-to-end without
a real Control Plane. This router is NOT registered in production (http mode).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User
from core import require_roles
from licensing import config, service, control_plane
from licensing.entitlement import VALID_STATES
from schemas_licensing import DevSetStateIn

router = APIRouter(prefix="/api/dev/licensing", tags=["licensing-dev"])


@router.post("/set-state")
async def set_state(payload: DevSetStateIn, user: User = Depends(require_roles("owner")), db: AsyncSession = Depends(get_db)):
    if payload.state not in VALID_STATES:
        raise HTTPException(status_code=422, detail=f"Invalid state; expected one of {sorted(VALID_STATES)}")
    seats = payload.seats_licensed if payload.seats_licensed is not None else config.DEV_DEFAULT_SEATS
    await control_plane.set_dev_subscription(db, state=payload.state, seats=int(seats), license_id=payload.license_id)
    result = await service.refresh(db, force=True)
    return {"ok": True, "applied": {"state": payload.state, "seats_licensed": int(seats)}, "refresh": result}
