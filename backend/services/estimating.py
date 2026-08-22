"""Estimating calculation engine — server-authoritative.

Terminology (documented, do NOT treat markup and margin as interchangeable):
  estimated_unit_cost = material_cost + labor_cost + equipment_cost + subcontract_cost   (per estimate unit)
  markup_percent      = (price - cost) / cost   * 100          # cost basis
  margin_percent      = (price - cost) / price  * 100          # price basis
  price from markup   : price = cost * (1 + markup/100)
  price from margin   : price = cost / (1 - margin/100)

Waste (kept separate, measured is never overwritten):
  measured_quantity                      -> user/roof input
  calculated_quantity = measured * (1 + waste_percent/100)     -> used for costing & pricing
  order_quantity      = calculated_quantity * conversion_factor (purchase UOM) — explicit, never guessed
"""
from __future__ import annotations
import math

# Common roofing units offered in the UI (users are NOT restricted to these).
STANDARD_UNITS = ["EA", "PC", "BDL", "SQ", "RL", "BX", "PL", "LF", "SF", "GAL", "PAIL"]


def r2(v: float) -> float:
    return round(float(v or 0), 2)


def r4(v: float) -> float:
    return round(float(v or 0), 4)


def calculated_quantity(measured_quantity: float, waste_percent: float) -> float:
    return r4((measured_quantity or 0) * (1 + (waste_percent or 0) / 100.0))


def unit_cost(material_cost=0, labor_cost=0, equipment_cost=0, subcontract_cost=0) -> float:
    return r4((material_cost or 0) + (labor_cost or 0) + (equipment_cost or 0) + (subcontract_cost or 0))


def price_from_markup(cost: float, markup_percent: float) -> float:
    return r4((cost or 0) * (1 + (markup_percent or 0) / 100.0))


def price_from_margin(cost: float, margin_percent: float) -> float:
    m = (margin_percent or 0) / 100.0
    if m >= 1:
        return 0.0
    return r4((cost or 0) / (1 - m)) if (1 - m) else 0.0


def markup_from_prices(cost: float, price: float) -> float:
    if not cost:
        return 0.0
    return r2(((price or 0) - cost) / cost * 100.0)


def margin_from_prices(cost: float, price: float) -> float:
    if not price:
        return 0.0
    return r2(((price or 0) - (cost or 0)) / price * 100.0)


def order_quantity(calc_qty: float, conversion_factor: float | None, round_up: bool = True) -> float | None:
    """Convert a waste-adjusted estimate quantity into supplier purchase UOM.
    conversion_factor = purchase-units per 1 estimate-unit. Returns None when not derivable."""
    if not conversion_factor:
        return None
    raw = (calc_qty or 0) * conversion_factor
    return float(math.ceil(raw)) if round_up else r4(raw)


def compute_line(line: dict) -> dict:
    """Given a raw line dict (costs + measured_quantity + waste_percent + markup/selling), return a
    fully computed line with authoritative quantity/selling_unit_price/line_total/cost fields.

    Pricing precedence:
      - if selling_unit_price explicitly provided (> 0) and pricing_mode != 'markup' -> use it, derive markup
      - elif markup_percent provided -> price = cost*(1+markup)
      - else -> selling_unit_price falls back to provided unit_price or cost
    """
    mat = float(line.get("material_cost") or 0)
    lab = float(line.get("labor_cost") or 0)
    equ = float(line.get("equipment_cost") or 0)
    sub = float(line.get("subcontract_cost") or 0)
    ucost = unit_cost(mat, lab, equ, sub)

    measured = float(line.get("measured_quantity") if line.get("measured_quantity") not in (None, "") else line.get("quantity") or 0)
    waste = float(line.get("waste_percent") or 0)
    qty = calculated_quantity(measured, waste)

    pricing_mode = line.get("pricing_mode")  # 'markup' | 'margin' | 'fixed' | None
    markup = line.get("markup_percent")
    sell = line.get("selling_unit_price")
    if sell in (None, ""):
        sell = line.get("unit_price")

    if pricing_mode == "markup" and markup is not None:
        sell = price_from_markup(ucost, float(markup))
    elif pricing_mode == "margin" and line.get("margin_percent") is not None:
        sell = price_from_margin(ucost, float(line["margin_percent"]))
    elif (sell in (None, "") or float(sell or 0) == 0) and markup is not None:
        sell = price_from_markup(ucost, float(markup))
    elif sell in (None, ""):
        sell = ucost
    sell = r4(sell)

    line["material_cost"], line["labor_cost"], line["equipment_cost"], line["subcontract_cost"] = mat, lab, equ, sub
    line["measured_quantity"] = r4(measured)
    line["waste_percent"] = r4(waste)
    line["quantity"] = qty
    line["selling_unit_price"] = sell
    line["unit_price"] = sell  # keep legacy field in sync (customer price)
    line["markup_percent"] = markup_from_prices(ucost, sell)
    line["line_total"] = r2(qty * sell)
    line["order_quantity"] = order_quantity(qty, line.get("conversion_factor"))
    line["_unit_cost"] = ucost
    line["_extended_cost"] = r2(qty * ucost)
    return line


def summarize(lines: list[dict], tax_rate: float = 0) -> dict:
    """Roll up computed lines into estimate-level cost vs selling metrics."""
    material = labor = equipment = subcontract = est_cost = selling = 0.0
    for ln in lines:
        q = float(ln.get("quantity") or 0)
        material += q * float(ln.get("material_cost") or 0)
        labor += q * float(ln.get("labor_cost") or 0)
        equipment += q * float(ln.get("equipment_cost") or 0)
        subcontract += q * float(ln.get("subcontract_cost") or 0)
        est_cost += float(ln.get("_extended_cost") or (q * float(ln.get("_unit_cost") or 0)))
        selling += float(ln.get("line_total") or 0)
    selling = r2(selling)
    est_cost = r2(est_cost)
    tax = r2(selling * (tax_rate or 0) / 100.0)
    gross_profit = r2(selling - est_cost)
    gross_margin = margin_from_prices(est_cost, selling)
    return {
        "material_cost": r2(material), "labor_cost": r2(labor), "equipment_cost": r2(equipment),
        "subcontract_cost": r2(subcontract), "estimated_total_cost": est_cost,
        "subtotal": selling, "tax": tax, "total": r2(selling + tax),
        "selling_price": selling, "gross_profit": gross_profit, "gross_margin_pct": gross_margin,
    }
