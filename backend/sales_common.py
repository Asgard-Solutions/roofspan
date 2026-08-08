from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Counter, IdempotencyKey


async def next_number(db: AsyncSession, name: str, prefix: str, width: int = 4) -> str:
    c = (await db.execute(select(Counter).where(Counter.name == name).with_for_update())).scalar_one_or_none()
    if not c:
        c = Counter(name=name, value=0)
        db.add(c)
        await db.flush()
    c.value += 1
    await db.flush()
    return f"{prefix}-{c.value:0{width}d}"


def compute_totals(items, tax_rate: float):
    """items: iterable with .quantity/.unit_price OR dicts. tax_rate is a percent."""
    subtotal = 0.0
    for it in items:
        q = getattr(it, "quantity", None) if not isinstance(it, dict) else it.get("quantity", 0)
        up = getattr(it, "unit_price", None) if not isinstance(it, dict) else it.get("unit_price", 0)
        subtotal += round((q or 0) * (up or 0), 2)
    subtotal = round(subtotal, 2)
    tax = round(subtotal * (tax_rate or 0) / 100.0, 2)
    return subtotal, tax, round(subtotal + tax, 2)


def line_total(q, up) -> float:
    return round((q or 0) * (up or 0), 2)


async def check_idempotency(db: AsyncSession, key: str | None, entity_type: str):
    if not key:
        return None
    row = await db.get(IdempotencyKey, key)
    if row and row.entity_type == entity_type:
        return row.entity_id
    return None


async def record_idempotency(db: AsyncSession, key: str | None, entity_type: str, entity_id):
    if key:
        db.add(IdempotencyKey(key=key, entity_type=entity_type, entity_id=str(entity_id)))


def enforce_version(entity, if_match: str | None, label: str):
    """Optimistic concurrency: if If-Match provided, it must equal current version."""
    if if_match is None or if_match == "":
        return
    try:
        v = int(if_match.strip().strip('"'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid If-Match header")
    if v != entity.version:
        raise HTTPException(status_code=409, detail=f"{label} was modified by someone else. Reload and try again.")
