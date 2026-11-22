import uuid

from fastapi import HTTPException

from core import ROLES
from models import User


async def resolve_assignee(db, user_id: str | None) -> User | None:
    """None clears; otherwise the user must exist, be active and hold an assignable role (422 if not)."""
    if not user_id:
        return None
    try:
        target = await db.get(User, uuid.UUID(str(user_id)))
    except ValueError:
        target = None
    if not target or not target.is_active or target.role not in ROLES:
        raise HTTPException(status_code=422, detail="Assignee must be an active user")
    return target
