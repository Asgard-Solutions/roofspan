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
    # Default = an explicit 'default' entry or a legacy blank entry with NO specific target. Supplier/
    # manufacturer/category/labor entries are NEVER treated as the estimate default.
    return next((e for e in entries if _is_default_entry(e)), None)


def _is_default_entry(e: PriceBookEntry) -> bool:
    if e.target_type == "default":
        return True
    if e.target_type in ("supplier", "manufacturer", "category", "labor", "assembly"):
        return False
    return not (e.material_id or e.assembly_id or e.supplier_id or e.manufacturer or e.category)


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


# ---------------------------------------------------------------------------
# Material effective Cost + Price (Decimal-authoritative). Distinct from the estimate line pricing
# above: this NEVER stores a price — it computes the live effective cost source and the Default Price
# Book price for display on Inventory / Material Detail. MWAC (avg_cost) is untouched.
# ---------------------------------------------------------------------------
from decimal import Decimal, ROUND_HALF_UP  # noqa: E402

from models import Material, Supplier  # noqa: E402
from services import inventory_core as inv_core  # noqa: E402

Q4 = Decimal("0.0001")


def _d(v):
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q4(v: Decimal | None):
    return v.quantize(Q4, rounding=ROUND_HALF_UP) if v is not None else None


def price_from_markup_d(cost: Decimal, markup_percent: Decimal) -> Decimal:
    return _q4(cost * (Decimal(1) + markup_percent / Decimal(100)))


def price_from_margin_d(cost: Decimal, margin_percent: Decimal) -> Decimal:
    m = margin_percent / Decimal(100)
    if m >= 1:
        return None
    return _q4(cost / (Decimal(1) - m))


async def resolve_effective_cost(db: AsyncSession, material: Material) -> dict:
    """Resolve the material's effective unit cost + its source, in priority order:
    preferred supplier cost -> best known cost -> standard_cost -> MWAC avg_cost -> none.
    The supplier that provides the cost basis is returned so a Supplier Price Book rule can be matched
    to the SAME supplier (never an arbitrary cheaper mapping)."""
    out = {"effective_cost": None, "effective_cost_source": None,
           "effective_cost_supplier_id": None, "effective_cost_supplier_name": None}

    async def _sup_name(sid):
        if not sid:
            return None
        s = await db.get(Supplier, sid)
        return s.name if s else None

    pref = await inv_core.preferred_supplier_material(db, material.id)
    if pref is not None and pref.current_cost is not None:
        out.update({"effective_cost": _q4(_d(pref.current_cost)), "effective_cost_source": "preferred_supplier",
                    "effective_cost_supplier_id": (str(pref.supplier_id) if pref.supplier_id else None),
                    "effective_cost_supplier_name": await _sup_name(pref.supplier_id)})
        return out
    best = await inv_core.best_known_supplier_material(db, material.id)
    if best is not None and best.current_cost is not None:
        out.update({"effective_cost": _q4(_d(best.current_cost)), "effective_cost_source": "best_known_cost",
                    "effective_cost_supplier_id": (str(best.supplier_id) if best.supplier_id else None),
                    "effective_cost_supplier_name": await _sup_name(best.supplier_id)})
        return out
    if material.standard_cost is not None:
        out.update({"effective_cost": _q4(_d(material.standard_cost)), "effective_cost_source": "standard_cost"})
        return out
    if material.avg_cost is not None:
        out.update({"effective_cost": _q4(_d(material.avg_cost)), "effective_cost_source": "mwac"})
        return out
    return out


async def resolve_material_rule(db: AsyncSession, price_book_id, material: Material,
                                cost_supplier_id) -> PriceBookEntry | None:
    """Most-specific-wins: Item -> Supplier(of the effective cost) -> Manufacturer -> Category -> Default."""
    if not price_book_id:
        return None
    entries = (await db.execute(select(PriceBookEntry).where(
        PriceBookEntry.price_book_id == price_book_id, PriceBookEntry.active.is_(True))
        .order_by(PriceBookEntry.sort))).scalars().all()
    hit = next((e for e in entries if e.target_type == "material" and e.material_id and str(e.material_id) == str(material.id)), None)
    if hit:
        return hit
    if cost_supplier_id:
        hit = next((e for e in entries if e.target_type == "supplier" and e.supplier_id and str(e.supplier_id) == str(cost_supplier_id)), None)
        if hit:
            return hit
    if material.manufacturer:
        mfr = material.manufacturer.strip().lower()
        hit = next((e for e in entries if e.target_type == "manufacturer" and (e.manufacturer or "").strip().lower() == mfr), None)
        if hit:
            return hit
    if material.category:
        cat = material.category.strip().lower()
        hit = next((e for e in entries if e.target_type == "category" and (e.category or "").strip().lower() == cat), None)
        if hit:
            return hit
    return next((e for e in entries if _is_default_entry(e)), None)


async def compute_material_pricing(db: AsyncSession, material: Material) -> dict:
    """Live effective Cost + Default-Price-Book Price for a material (never stored). Returns full
    provenance so the UI can explain both numbers. If no cost basis exists, price is None (never $0)."""
    out = await resolve_effective_cost(db, material)
    out.update({"effective_price": None, "price_book_id": None, "price_book_name": None,
                "matched_rule_id": None, "matched_rule_type": None, "matched_rule_label": None})
    cost = out["effective_cost"]
    if cost is None:
        return out  # never fabricate a $0 price
    pb_id = await default_price_book_id(db)
    if not pb_id:
        return out  # no default price book -> price stays None (missing-default is explicit)
    pb = await db.get(PriceBook, pb_id)
    out["price_book_id"] = str(pb_id)
    out["price_book_name"] = pb.name if pb else None
    rule = await resolve_material_rule(db, pb_id, material, out["effective_cost_supplier_id"])
    if not rule:
        return out
    price = None
    if rule.rule_type == "fixed" and rule.fixed_price is not None:
        price = _q4(_d(rule.fixed_price))
    elif rule.rule_type == "markup" and rule.markup_percent is not None:
        price = price_from_markup_d(cost, _d(rule.markup_percent))
    elif rule.rule_type == "margin" and rule.margin_percent is not None:
        price = price_from_margin_d(cost, _d(rule.margin_percent))
    if price is None:
        return out
    label = rule.label
    if not label:
        rv = rule_value(rule)
        suffix = f"{rv}%" if rule.rule_type in ("markup", "margin") else f"${rv}"
        base = {"material": "Item", "supplier": (out["effective_cost_supplier_name"] or "Supplier"),
                "manufacturer": (material.manufacturer or "Manufacturer"),
                "category": (material.category or "Category"), "default": "Default"}.get(rule.target_type, rule.target_type)
        label = f"{base} — {rule.rule_type} {suffix}"
    out.update({"effective_price": price, "matched_rule_id": str(rule.id),
                "matched_rule_type": rule.rule_type, "matched_rule_label": label})
    return out
