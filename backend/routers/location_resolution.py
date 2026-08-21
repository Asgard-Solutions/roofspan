from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import get_current_user
from db import get_db
from location_upgrade import RESOLUTION_VERSION
from models import IntegrationSetting, Property, User

router = APIRouter(prefix="/api/location-resolution", tags=["location-resolution"])


def _loc(prop: Property) -> dict:
    raw = prop.raw if isinstance(prop.raw, dict) else {}
    value = raw.get("roofspan_location")
    return value if isinstance(value, dict) else {}


@router.get("/progress")
async def location_resolution_progress(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    props = (await db.execute(select(Property).where(Property.source == "rentcast"))).scalars().all()
    integration = (
        await db.execute(select(IntegrationSetting).where(IntegrationSetting.provider == "mapbox"))
    ).scalar_one_or_none()
    configured = bool(integration and integration.enabled and integration.secret_ciphertext)

    counts = {
        "total": len(props),
        "pending": 0,
        "resolved": 0,
        "address_only": 0,
        "unresolved": 0,
        "retry_pending": 0,
        "cached": 0,
    }
    reasons = Counter()
    accuracy_types = Counter()

    for prop in props:
        loc = _loc(prop)
        current = loc.get("auto_resolution_version") == RESOLUTION_VERSION
        status = loc.get("geocoder_status")
        reason = loc.get("geocoder_reason") or "unknown"

        if not current:
            if status == "error" or loc.get("resolution_state") == "retry_pending":
                counts["retry_pending"] += 1
                reasons[reason] += 1
            else:
                counts["pending"] += 1
            continue

        if loc.get("cached_permanently"):
            counts["cached"] += 1
        if loc.get("location_resolved") or status == "located":
            counts["resolved"] += 1
            accuracy_types[loc.get("mapbox_accuracy") or "unknown"] += 1
        else:
            counts["unresolved"] += 1
            reasons[reason] += 1

    attempted = counts["total"] - counts["pending"]
    percent = round((attempted / counts["total"]) * 100, 1) if counts["total"] else 100.0
    complete = counts["pending"] == 0
    if counts["total"] == 0:
        state = "idle"
    elif not configured and counts["pending"]:
        state = "provider_required"
    elif not complete:
        state = "processing"
    elif counts["retry_pending"]:
        state = "complete_with_retries"
    else:
        state = "complete"

    return {
        **counts,
        "attempted": attempted,
        "percent": percent,
        "pass_complete": complete,
        "state": state,
        "provider": "mapbox",
        "provider_configured": configured,
        "resolver_version": RESOLUTION_VERSION,
        "rejection_breakdown": [
            {"reason": reason, "count": count}
            for reason, count in reasons.most_common()
        ],
        "accuracy_breakdown": [
            {"accuracy_type": accuracy_type, "count": count}
            for accuracy_type, count in accuracy_types.most_common()
        ],
    }
