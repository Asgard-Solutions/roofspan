"""Price Book application — deterministic rule resolution for estimate lines.

Priority (documented, deterministic):
  1. Exact material rule   (PriceBookEntry.target_type='material' AND material_id matches)
  2. Assembly rule         (PriceBookEntry.target_type='assembly' AND assembly_id matches)
  3. General/default rule   (active entry with NO material_id AND NO assembly_id)
  4. Otherwise -> no rule (caller keeps existing manual behaviour; NO fallback markup is invented)

Rule kinds: fixed (selling price), markup % (on cost), margin % (on price). Applied sell + the rule
used are SNAPSHOTTED onto the estimate line so future Price Book edits never alter existing estimates.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import PriceBook, PriceBookEntry
from services import estimating as calc


async def default_price_book_id(db: AsyncSession):
    pb = (await db.execute(select(PriceBook).where(PriceBook.is_default.is_(True), PriceBook.active.is_(True)))).scalars().first()
    if not pb:
        pb = (await db.execute(select(PriceBook).where(PriceBook.active.is_(True)).order_by(PriceBook.created_at))).scalars().first()
    return pb.id if pb else None


async def find_rule(db: AsyncSession, price_book_id, material_id=None, assembly_id=None) -> PriceBookEntry | None:
    if not price_book_id:
        return None
    entries = (await db.execute(select(PriceBookEntry).where(
        PriceBookEntry.price_book_id == price_book_id, PriceBookEntry.active.is_(True))
        .order_by(PriceBookEntry.sort))).scalars().all()
    if material_id:
        m = next((e for e in entries if e.target_type == "material" and str(e.material_id) == str(material_id)), None)
        if m:
            return m
    if assembly_id:
        a = next((e for e in entries if e.target_type == "assembly" and str(e.assembly_id) == str(assembly_id)), None)
        if a:
            return a
    return next((e for e in entries if not e.material_id and not e.assembly_id), None)


def rule_value(entry: PriceBookEntry):
    if entry.rule_type == "fixed":
        return entry.fixed_price
    if entry.rule_type == "markup":
        return entry.markup_percent
    if entry.rule_type == "margin":
        return entry.margin_percent
    return None


def apply_rule(entry: PriceBookEntry, unit_cost: float) -> float | None:
    """Return the selling unit price produced by the rule, or None if the rule has no usable value."""
    v = rule_value(entry)
    if v is None:
        return None
    if entry.rule_type == "fixed":
        return calc.r4(v)
    if entry.rule_type == "markup":
        return calc.price_from_markup(unit_cost, float(v))
    if entry.rule_type == "margin":
        return calc.price_from_margin(unit_cost, float(v))
    return None
