"""Actual Job Costing — server-authoritative costing engine (Decimal, NUMERIC-backed).

Batch 1 scope:
  * estimated_baseline(): immutable historical baseline from the accepted quote/package internal cost
    snapshot (primary), falling back to the linked estimate snapshot for category detail. Never
    recomputed from current estimates or current supplier prices. Marked "none" (No Estimate Baseline)
    when neither source carries usable historical cost.
  * material_actual_costs(): actual material cost derived ONLY from the inventory ledger cost snapshots
    (job_issue / job_return / waste|damage|loss). Reservations and open POs are never actual cost.

Money is computed in Decimal and returned quantized to 4 dp (costs) / 2 dp (margin %). Sales role must
never receive this data — enforced at the router layer.
"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import (Job, Quote, QuoteLineItem, QuotePackage, EstimateLineItem,
                    JobMaterial, Material, InventoryTxn, ActualCostEntry, JobCostSnapshot)

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
ZERO = Decimal("0")

_CONSUME = "job_issue"
_RETURN = "job_return"
_DISPOSE = ("waste", "damage", "loss")
COST_CATEGORIES = ("labor", "equipment", "subcontract", "permits", "disposal", "other")


def _d(v):
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q4(v):
    return (_d(v) or ZERO).quantize(Q4, rounding=ROUND_HALF_UP)


def _q2(v):
    return (_d(v) or ZERO).quantize(Q2, rounding=ROUND_HALF_UP)


def _f4(v):
    return float(_q4(v))


def _f2(v):
    return float(_q2(v))


def _margin_pct(selling: Decimal, cost: Decimal) -> Decimal:
    if selling and selling != 0:
        return _q2((selling - cost) / selling * Decimal(100))
    return ZERO


async def _accepted_quote_lines(db: AsyncSession, q: Quote):
    """The quote lines that represent the version of work actually sold (accepted package or base)."""
    stmt = select(QuoteLineItem).where(QuoteLineItem.quote_id == q.id)
    pkg = None
    if q.multi_package:
        if not q.accepted_package_id:
            return [], None
        stmt = stmt.where(QuoteLineItem.package_id == q.accepted_package_id)
        pkg = await db.get(QuotePackage, q.accepted_package_id)
    else:
        stmt = stmt.where(QuoteLineItem.package_id.is_(None))
    lines = (await db.execute(stmt)).scalars().all()
    return lines, pkg


async def estimated_material_map(db: AsyncSession, job: Job) -> dict:
    """{material_id(str): estimated_cost Decimal} from the accepted quote's internal cost snapshot."""
    out: dict = {}
    if not job.quote_id:
        return out
    q = await db.get(Quote, job.quote_id)
    if not q:
        return out
    lines, _ = await _accepted_quote_lines(db, q)
    for ln in lines:
        if not ln.material_id:
            continue
        cost = (_d(ln.quantity) or ZERO) * (_d(ln.total_unit_cost) or ZERO)
        key = str(ln.material_id)
        out[key] = _q4((out.get(key) or ZERO) + cost)
    return out


async def estimated_baseline(db: AsyncSession, job: Job) -> dict:
    """Immutable estimated baseline. Priority: accepted quote/package internal cost snapshot (primary),
    linked estimate snapshot for category breakdown. Never recomputed from live prices."""
    empty = {
        "baseline_status": "none", "source": {},
        "estimated_material_cost": 0.0, "estimated_labor_cost": 0.0, "estimated_equipment_cost": 0.0,
        "estimated_subcontract_cost": 0.0, "estimated_other_cost": 0.0, "estimated_total_cost": 0.0,
        "estimated_selling": 0.0, "estimated_gross_profit": 0.0, "estimated_gross_margin_percent": 0.0,
    }
    if not job.quote_id:
        return empty
    q = await db.get(Quote, job.quote_id)
    if not q:
        return empty
    lines, pkg = await _accepted_quote_lines(db, q)
    if not lines:
        return empty

    # Primary: total internal cost snapshot from the sold quote lines.
    quote_total_cost = ZERO
    quote_material_cost = ZERO
    for ln in lines:
        ext = (_d(ln.quantity) or ZERO) * (_d(ln.total_unit_cost) or ZERO)
        quote_total_cost += ext
        if ln.material_id:
            quote_material_cost += ext

    # Category detail from the linked estimate snapshot (informational; non-material breakdown).
    material = labor = equipment = subcontract = ZERO
    have_estimate = False
    if q.estimate_id:
        elines = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == q.estimate_id))).scalars().all()
        for e in elines:
            qy = _d(e.quantity) or ZERO
            material += qy * (_d(e.material_cost) or ZERO)
            labor += qy * (_d(e.labor_cost) or ZERO)
            equipment += qy * (_d(e.equipment_cost) or ZERO)
            subcontract += qy * (_d(e.subcontract_cost) or ZERO)
        have_estimate = bool(elines)
    estimate_total = material + labor + equipment + subcontract

    selling = _d(pkg.total if pkg else q.total) or ZERO

    if quote_total_cost > 0:
        status = "quote"
        total_cost = quote_total_cost
        # material category from quote (precise per sold lines); non-material split from estimate if present.
        est_material = quote_material_cost
        est_labor, est_equipment, est_subcontract = (labor, equipment, subcontract) if have_estimate else (ZERO, ZERO, ZERO)
        est_other = total_cost - est_material - est_labor - est_equipment - est_subcontract
        if est_other < 0:
            est_other = ZERO
    elif estimate_total > 0:
        status = "estimate"
        total_cost = estimate_total
        est_material, est_labor, est_equipment, est_subcontract, est_other = material, labor, equipment, subcontract, ZERO
    else:
        return empty

    gross_profit = selling - total_cost
    return {
        "baseline_status": status,
        "source": {"quote_id": str(q.id), "quote_number": q.number,
                   "package_id": str(pkg.id) if pkg else None, "package_name": pkg.name if pkg else None,
                   "estimate_id": str(q.estimate_id) if q.estimate_id else None},
        "estimated_material_cost": _f4(est_material),
        "estimated_labor_cost": _f4(est_labor),
        "estimated_equipment_cost": _f4(est_equipment),
        "estimated_subcontract_cost": _f4(est_subcontract),
        "estimated_other_cost": _f4(est_other),
        "estimated_total_cost": _f4(total_cost),
        "estimated_selling": _f2(selling),
        "estimated_gross_profit": _f2(gross_profit),
        "estimated_gross_margin_percent": float(_margin_pct(selling, total_cost)),
    }


async def material_actual_costs(db: AsyncSession, job: Job) -> dict:
    """Per-material actual cost from the ledger cost snapshots + estimated cost per material.
    actual_material_cost = issued_cost - returned_cost + waste_cost (all from cost snapshots)."""
    est_map = await estimated_material_map(db, job)

    # distinct materials that appear on the job plan OR have cost-bearing ledger activity for this job.
    mids = set(est_map.keys())
    for r in (await db.execute(select(JobMaterial.material_id).where(JobMaterial.job_id == job.id))).scalars().all():
        mids.add(str(r))
    for r in (await db.execute(select(InventoryTxn.material_id).where(
            InventoryTxn.job_id == job.id,
            InventoryTxn.reason.in_((_CONSUME, _RETURN) + _DISPOSE)).distinct())).scalars().all():
        mids.add(str(r))

    lines = []
    tot_est = tot_actual = tot_issued = tot_returned = tot_waste = ZERO
    any_missing = False
    for mid in mids:
        rows = (await db.execute(select(InventoryTxn.reason, InventoryTxn.delta, InventoryTxn.extended_cost).where(
            InventoryTxn.material_id == mid, InventoryTxn.job_id == job.id,
            InventoryTxn.reason.in_((_CONSUME, _RETURN) + _DISPOSE)))).all()
        issued_qty = returned_qty = waste_qty = ZERO
        issued_cost = returned_cost = waste_cost = ZERO
        missing = False
        for reason, delta, ext in rows:
            qmag = abs(_d(delta) or ZERO)
            if reason == _CONSUME:
                issued_qty += qmag
                if ext is None and qmag > 0:
                    missing = True
                else:
                    issued_cost += -_d(ext) if ext is not None else ZERO
            elif reason == _RETURN:
                returned_qty += qmag
                if ext is not None:
                    returned_cost += _d(ext)
            else:  # waste / damage / loss
                waste_qty += qmag
                if ext is None and qmag > 0:
                    missing = True
                else:
                    waste_cost += -_d(ext) if ext is not None else ZERO

        actual = issued_cost - returned_cost + waste_cost
        est = est_map.get(mid, ZERO)
        m = await db.get(Material, mid)
        if missing:
            status = "missing_cost_basis"
            any_missing = True
        elif issued_qty > 0 or waste_qty > 0:
            status = "complete"
        else:
            status = "no_activity"
        lines.append({
            "material_id": mid, "material_name": m.name if m else "?", "unit": m.unit if m else "ea",
            "issued_quantity": _f4(issued_qty), "returned_quantity": _f4(returned_qty),
            "waste_quantity": _f4(waste_qty), "net_used_quantity": _f4(issued_qty - returned_qty),
            "issued_cost": _f4(issued_cost), "returned_cost": _f4(returned_cost), "waste_cost": _f4(waste_cost),
            "actual_material_cost": _f4(actual), "estimated_material_cost": _f4(est),
            "variance": _f4(actual - est), "cost_basis_status": status,
        })
        tot_est += est
        tot_actual += actual
        tot_issued += issued_cost
        tot_returned += returned_cost
        tot_waste += waste_cost

    lines.sort(key=lambda x: x["material_name"].lower())
    return {
        "total_estimated_material_cost": _f4(tot_est),
        "total_actual_material_cost": _f4(tot_actual),
        "total_issued_cost": _f4(tot_issued),
        "total_returned_cost": _f4(tot_returned),
        "total_waste_cost": _f4(tot_waste),
        "material_variance": _f4(tot_actual - tot_est),
        "has_missing_cost_basis": any_missing,
        "lines": lines,
    }


async def manual_actual_costs(db: AsyncSession, job: Job) -> dict:
    """Manual non-material actual costs recorded against the job, grouped by category."""
    rows = (await db.execute(select(ActualCostEntry).where(ActualCostEntry.job_id == job.id)
                             .order_by(ActualCostEntry.created_at))).scalars().all()
    totals = {c: ZERO for c in COST_CATEGORIES}
    entries = []
    for e in rows:
        amt = _d(e.amount) or ZERO
        cat = e.category if e.category in COST_CATEGORIES else "other"
        totals[cat] += amt
        entries.append({
            "id": str(e.id), "category": cat, "description": e.description, "amount": _f4(amt),
            "quantity": (_f4(e.quantity) if e.quantity is not None else None),
            "unit_rate": (_f4(e.unit_rate) if e.unit_rate is not None else None),
            "incurred_on": e.incurred_on.isoformat() if e.incurred_on else None,
            "notes": e.notes, "created_by": e.created_by,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    total = sum(totals.values(), ZERO)
    return {
        "category_totals": {c: _f4(totals[c]) for c in COST_CATEGORIES},
        "total_manual_cost": _f4(total),
        "entries": entries,
    }


async def summary(db: AsyncSession, job: Job, baseline=None, material=None, manual=None) -> dict:
    """Full estimated-vs-actual roll-up, variance, gross profit/margin and completeness status.
    Revenue = the sold price (accepted quote/package total) — the immutable historical baseline."""
    baseline = baseline if baseline is not None else await estimated_baseline(db, job)
    material = material if material is not None else await material_actual_costs(db, job)
    manual = manual if manual is not None else await manual_actual_costs(db, job)

    revenue = _d(baseline["estimated_selling"]) or ZERO
    est = {
        "material": _d(baseline["estimated_material_cost"]) or ZERO,
        "labor": _d(baseline["estimated_labor_cost"]) or ZERO,
        "equipment": _d(baseline["estimated_equipment_cost"]) or ZERO,
        "subcontract": _d(baseline["estimated_subcontract_cost"]) or ZERO,
        "permits": ZERO, "disposal": ZERO,
        "other": _d(baseline["estimated_other_cost"]) or ZERO,
    }
    est["total"] = _d(baseline["estimated_total_cost"]) or ZERO
    mt = manual["category_totals"]
    act = {
        "material": _d(material["total_actual_material_cost"]) or ZERO,
        "labor": _d(mt["labor"]) or ZERO, "equipment": _d(mt["equipment"]) or ZERO,
        "subcontract": _d(mt["subcontract"]) or ZERO, "permits": _d(mt["permits"]) or ZERO,
        "disposal": _d(mt["disposal"]) or ZERO, "other": _d(mt["other"]) or ZERO,
    }
    act["total"] = sum(act[c] for c in ("material", "labor", "equipment", "subcontract", "permits", "disposal", "other"))

    est_gp = revenue - est["total"]
    act_gp = revenue - act["total"]
    keys = ("material", "labor", "equipment", "subcontract", "permits", "disposal", "other", "total")
    variance = {k: (act[k] - est[k]) for k in keys}

    if baseline["baseline_status"] == "none":
        status = "no_estimate_baseline"
    elif material["has_missing_cost_basis"]:
        status = "missing_cost_basis"
    elif job.status == "completed":
        status = "complete"
    elif act["total"] > 0:
        status = "partial"
    else:
        status = "not_started"

    return {
        "revenue": _f2(revenue),
        "estimated": {**{k: _f4(est[k]) for k in keys}, "gross_profit": _f2(est_gp),
                      "gross_margin_percent": float(_margin_pct(revenue, est["total"]))},
        "actual": {**{k: _f4(act[k]) for k in keys}, "gross_profit": _f2(act_gp),
                   "gross_margin_percent": float(_margin_pct(revenue, act["total"]))},
        "variance": {**{k: _f4(variance[k]) for k in keys}, "gross_profit": _f2(act_gp - est_gp)},
        "costing_status": status,
    }


async def costing(db: AsyncSession, job: Job) -> dict:
    """Combined job costing payload: baseline + material actual + manual actual + full summary."""
    baseline = await estimated_baseline(db, job)
    material = await material_actual_costs(db, job)
    manual = await manual_actual_costs(db, job)
    summ = await summary(db, job, baseline, material, manual)
    latest = (await db.execute(select(JobCostSnapshot).where(JobCostSnapshot.job_id == job.id)
                               .order_by(JobCostSnapshot.created_at.desc()).limit(1))).scalars().first()
    return {
        "job_id": str(job.id), "job_number": job.number, "job_status": job.status,
        "baseline": baseline, "material_actual": material, "manual_actual": manual,
        "summary": summ,
        "latest_snapshot_at": latest.created_at.isoformat() if latest and latest.created_at else None,
    }


async def build_snapshot(db: AsyncSession, job: Job, trigger: str, user_email: str | None) -> JobCostSnapshot:
    """Create an IMMUTABLE snapshot of the job's current costing. Never mutates prior snapshots."""
    payload = await costing(db, job)
    summ = payload["summary"]
    snap = JobCostSnapshot(
        job_id=job.id, job_number=job.number, trigger=trigger,
        baseline_status=payload["baseline"]["baseline_status"], costing_status=summ["costing_status"],
        revenue=_d(summ["revenue"]), estimated_total_cost=_d(summ["estimated"]["total"]),
        actual_total_cost=_d(summ["actual"]["total"]),
        estimated_gross_profit=_d(summ["estimated"]["gross_profit"]),
        actual_gross_profit=_d(summ["actual"]["gross_profit"]),
        actual_gross_margin_percent=_d(summ["actual"]["gross_margin_percent"]),
        total_variance=_d(summ["variance"]["total"]), payload=payload, created_by=user_email,
    )
    db.add(snap)
    await db.flush()
    return snap


# ---------------------------------------------------------------------------
# Reporting (cross-job) — all cost/profitability data, router-gated to non-Sales roles.
# ---------------------------------------------------------------------------
from models import PurchaseOrder, POLineItem, Supplier  # noqa: E402


async def profitability_report(db: AsyncSession, status: str | None = None, limit: int = 500) -> dict:
    """Per-job estimated-vs-actual profitability. Includes jobs with a baseline or any actual activity."""
    stmt = select(Job).order_by(Job.created_at.desc())
    if status:
        stmt = stmt.where(Job.status == status)
    jobs = (await db.execute(stmt.limit(limit))).scalars().all()
    rows = []
    tot_rev = tot_cost = tot_est = tot_gp = ZERO
    for j in jobs:
        b = await estimated_baseline(db, j)
        mat = await material_actual_costs(db, j)
        man = await manual_actual_costs(db, j)
        summ = await summary(db, j, b, mat, man)
        actual_total = _d(summ["actual"]["total"]) or ZERO
        if b["baseline_status"] == "none" and actual_total <= 0:
            continue
        rev = _d(summ["revenue"]) or ZERO
        est = _d(summ["estimated"]["total"]) or ZERO
        rows.append({
            "job_id": str(j.id), "job_number": j.number, "job_status": j.status,
            "costing_status": summ["costing_status"], "revenue": _f2(rev),
            "estimated_cost": _f2(est), "actual_cost": _f2(actual_total),
            "estimated_gross_profit": summ["estimated"]["gross_profit"],
            "actual_gross_profit": summ["actual"]["gross_profit"],
            "actual_gross_margin_percent": summ["actual"]["gross_margin_percent"],
            "total_variance": summ["variance"]["total"],
        })
        tot_rev += rev
        tot_cost += actual_total
        tot_est += est
        tot_gp += _d(summ["actual"]["gross_profit"]) or ZERO
    return {"rows": rows, "totals": {
        "revenue": _f2(tot_rev), "estimated_cost": _f2(tot_est), "actual_cost": _f2(tot_cost),
        "actual_gross_profit": _f2(tot_gp),
        "actual_gross_margin_percent": float(_margin_pct(tot_rev, tot_cost)),
        "total_variance": _f4((tot_cost - tot_est))}}


async def material_variance_report(db: AsyncSession, limit: int = 1000) -> dict:
    """Aggregate estimated vs actual material cost per material across all jobs with activity."""
    jobs = (await db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit))).scalars().all()
    agg: dict = {}
    for j in jobs:
        mat = await material_actual_costs(db, j)
        for l in mat["lines"]:
            a = agg.setdefault(l["material_id"], {
                "material_id": l["material_id"], "material_name": l["material_name"],
                "estimated_cost": ZERO, "actual_cost": ZERO, "waste_cost": ZERO,
                "issued_quantity": ZERO, "waste_quantity": ZERO, "missing_basis": False})
            a["estimated_cost"] += _d(l["estimated_material_cost"]) or ZERO
            a["actual_cost"] += _d(l["actual_material_cost"]) or ZERO
            a["waste_cost"] += _d(l["waste_cost"]) or ZERO
            a["issued_quantity"] += _d(l["issued_quantity"]) or ZERO
            a["waste_quantity"] += _d(l["waste_quantity"]) or ZERO
            if l["cost_basis_status"] == "missing_cost_basis":
                a["missing_basis"] = True
    rows = []
    for a in agg.values():
        if a["actual_cost"] == 0 and a["estimated_cost"] == 0:
            continue
        rows.append({
            "material_id": a["material_id"], "material_name": a["material_name"],
            "estimated_cost": _f4(a["estimated_cost"]), "actual_cost": _f4(a["actual_cost"]),
            "variance": _f4(a["actual_cost"] - a["estimated_cost"]), "waste_cost": _f4(a["waste_cost"]),
            "issued_quantity": _f4(a["issued_quantity"]), "waste_quantity": _f4(a["waste_quantity"]),
            "missing_cost_basis": a["missing_basis"]})
    rows.sort(key=lambda x: x["variance"], reverse=True)
    return {"rows": rows}


async def waste_cost_report(db: AsyncSession) -> dict:
    """Waste / damage / loss cost grouped by material (from ledger cost snapshots)."""
    rows = (await db.execute(
        select(InventoryTxn.material_id, Material.name,
               func.coalesce(func.sum(-InventoryTxn.extended_cost), 0),
               func.coalesce(func.sum(func.abs(InventoryTxn.delta)), 0))
        .join(Material, Material.id == InventoryTxn.material_id)
        .where(InventoryTxn.reason.in_(_DISPOSE))
        .group_by(InventoryTxn.material_id, Material.name))).all()
    out = []
    total = ZERO
    for mid, name, cost, qty in rows:
        c = _d(cost) or ZERO
        total += c
        out.append({"material_id": str(mid), "material_name": name,
                    "waste_cost": _f4(c), "waste_quantity": _f4(qty)})
    out.sort(key=lambda x: x["waste_cost"], reverse=True)
    return {"rows": out, "total_waste_cost": _f4(total)}


async def supplier_cost_impact_report(db: AsyncSession) -> dict:
    """Actual purchased cost of received material grouped by supplier (received_qty * unit_cost)."""
    rows = (await db.execute(
        select(PurchaseOrder.supplier_id, Supplier.name,
               func.coalesce(func.sum(POLineItem.received_quantity * POLineItem.unit_cost), 0),
               func.count(func.distinct(PurchaseOrder.id)))
        .join(POLineItem, POLineItem.po_id == PurchaseOrder.id)
        .outerjoin(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(POLineItem.received_quantity > 0)
        .group_by(PurchaseOrder.supplier_id, Supplier.name))).all()
    out = []
    total = ZERO
    for sid, name, cost, po_count in rows:
        c = _d(cost) or ZERO
        total += c
        out.append({"supplier_id": str(sid) if sid else None, "supplier_name": name or "(unassigned)",
                    "received_cost": _f2(c), "po_count": int(po_count)})
    out.sort(key=lambda x: x["received_cost"], reverse=True)
    return {"rows": out, "total_received_cost": _f2(total)}
