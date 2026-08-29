from fastapi import APIRouter, Depends

from core import get_current_user
from models import User
from visit_outcomes import VISIT_OUTCOMES

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/visit-outcomes")
async def list_visit_outcomes(user: User = Depends(get_current_user)):
    """Canonical RoofSpan visit outcomes — the ONE backend source Office and Field render from."""
    return {"outcomes": [{"value": v, "label": label} for v, label in VISIT_OUTCOMES.items()]}
