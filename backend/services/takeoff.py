"""Versioned roof takeoff service with explicit revision/change guards."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AppConfig, Estimate, EstimateLineItem, Assembly, AssemblyItem, Material, Supplier,
    MeasurementRevision, MeasurementSet,
)
from takeoff_models import (
    TakeoffTemplate, TakeoffTemplateRevision, TakeoffRule, EstimateTakeoff, EstimateTakeoffLine,
)
from services import measurements as measurement_svc
from services import estimating as calc
from services import inventory_core as inv_core
from services import pricing as pricing_svc
from services.takeoff_core import (
    resolve_waste_percent, weighted_roof_waste_percent, metric_value,
    package_quantity, normalized_product_coverage,
)


async def company_default_waste(db: AsyncSession) -> float:
    row = await db.get(AppConfig, "takeoff_settings")
    value = row.value if row and isinstance(row.value, dict) else {}
    try:
        return float(value.get("default_waste_percent", 10.0))
    except (TypeError, ValueError):
        return 10.0


async def set_company_default_waste(db: AsyncSession, value: float) -> float:
    if value < 0 or value > 100:
        raise HTTPException(status_code=422, detail="Default waste percent must be between 0 and 100")
    row = await db.get(AppConfig, "takeoff_settings")
    if row:
        row.value = {**(row.value or {}), "default_waste_percent": float(value)}
    else:
        db.add(AppConfig(key="takeoff_settings", value={"default_waste_percent": float(value)}))
    await db.flush()
    return float(value)


async def snapshot_assembly(db: AsyncSession, assembly_id: str) -> tuple[Assembly, list[dict]]:
    assembly = await db.get(Assembly, assembly_id)
    if not assembly or not assembly.active:
        raise HTTPException(status_code=422, detail=f"Assembly {assembly_id} was not found or is inactive")
    items = (await db.execute(
        select(AssemblyItem).where(AssemblyItem.assembly_id == assembly.id).order_by(AssemblyItem.sort)
    )).scalars().all()
    if not items:
        raise HTTPException(status_code=422, detail=f"Assembly '{assembly.name}' has no items")
    snapshot = [{
        "material_id": str(it.material_id) if it.material_id else None,
        "description": it.description,
        "quantity_factor": float(it.quantity_factor or 0),
        "unit": it.unit,
        "waste_override": it.waste_override,
        "is_labor": bool(it.is_labor),
        "sort": it.sort,
    } for it in items]
    return assembly, snapshot


async def next_template_revision_number(db: AsyncSession, template_id) -> int:
    rows = (await db.execute(select(TakeoffTemplateRevision.revision_number).where(
        TakeoffTemplateRevision.template_id == template_id
    ))).scalars().all()
    return max([int(x) for x in rows] or [0]) + 1


async def create_template_revision(db: AsyncSession, template: TakeoffTemplate, payload, user) -> TakeoffTemplateRevision:
    rev = TakeoffTemplateRevision(
        template_id=template.id,
        revision_number=await next_template_revision_number(db, template.id),
        default_waste_percent=float(payload.default_waste_percent),
        notes=payload.notes,
        created_by=getattr(user, "email", None),
    )
    db.add(rev)
    await db.flush()
    for idx, rule_in in enumerate(payload.rules or []):
        assembly, snap = await snapshot_assembly(db, rule_in.assembly_id)
        db.add(TakeoffRule(
            template_revision_id=rev.id,
            name=rule_in.name,
            metric_key=rule_in.metric_key,
            quantity_factor=float(rule_in.quantity_factor or 0),
            apply_waste=bool(rule_in.apply_waste),
            assembly_id=assembly.id,
            assembly_version=assembly.version,
            assembly_name=assembly.name,
            assembly_waste_percent=rule_in.assembly_waste_percent,
            coverage_per_package=rule_in.coverage_per_package,
            assembly_snapshot={"unit_basis": assembly.unit_basis, "items": snap},
            sort=idx,
        ))
    await db.flush()
    return rev


async def template_revision_out(db: AsyncSession, rev: TakeoffTemplateRevision) -> dict:
    template = await db.get(TakeoffTemplate, rev.template_id)
    rules = (await db.execute(select(TakeoffRule).where(
        TakeoffRule.template_revision_id == rev.id
    ).order_by(TakeoffRule.sort))).scalars().all()
    return {
        "id": str(rev.id), "template_id": str(rev.template_id), "template_name": template.name if template else None,
        "revision_number": rev.revision_number, "default_waste_percent": rev.default_waste_percent,
        "notes": rev.notes, "created_by": rev.created_by, "created_at": rev.created_at,
        "rules": [{
            "id": str(r.id), "name": r.name, "metric_key": r.metric_key, "quantity_factor": r.quantity_factor,
            "apply_waste": r.apply_waste, "assembly_id": str(r.assembly_id) if r.assembly_id else None,
            "assembly_version": r.assembly_version, "assembly_name": r.assembly_name,
            "assembly_waste_percent": r.assembly_waste_percent, "coverage_per_package": r.coverage_per_package,
        } for r in rules],
    }


def _line_signature(line) -> dict:
    def g(name, default=None):
        return line.get(name, default) if isinstance(line, dict) else getattr(line, name, default)
    return {
        "description": g("description") or "",
        "material_id": str(g("material_id")) if g("material_id") else None,
        "measured_quantity": round(float(g("measured_quantity", 0) or 0), 4),
        "waste_percent": round(float(g("waste_percent", 0) or 0), 4),
        "quantity": round(float(g("quantity", 0) or 0), 4),
        "selling_unit_price": round(float(g("selling_unit_price", 0) or 0), 4),
        "assembly_id": str(g("assembly_id")) if g("assembly_id") else None,
        "assembly_version": g("assembly_version"),
    }


async def _existing_generated_state(db: AsyncSession, estimate_id) -> tuple[list[str], list[dict]]:
    takeoffs = (await db.execute(select(EstimateTakeoff.id).where(
        EstimateTakeoff.estimate_id == estimate_id
    ))).scalars().all()
    if not takeoffs:
        return [], []
    links = (await db.execute(select(EstimateTakeoffLine).where(
        EstimateTakeoffLine.takeoff_id.in_(takeoffs), EstimateTakeoffLine.estimate_line_item_id.is_not(None)
    ))).scalars().all()
    ids, modified = [], []
    for link in links:
        line = await db.get(EstimateLineItem, link.estimate_line_item_id)
        if not line:
            continue
        lid = str(line.id)
        ids.append(lid)
        original = (link.provenance or {}).get("generated_line_snapshot")
        if original and _line_signature(line) != original:
            modified.append({"line_id": lid, "description": line.description})
    return list(dict.fromkeys(ids)), modified


async def _validated_inputs(db: AsyncSession, estimate_id: str, payload):
    estimate = await db.get(Estimate, estimate_id)
    if not estimate:
        raise HTTPException(status_code=404, detail="Estimate not found")
    measurement = await db.get(MeasurementRevision, payload.measurement_revision_id)
    if not measurement:
        raise HTTPException(status_code=404, detail="Measurement revision not found")
    if measurement.status not in ("office_verified", "locked"):
        raise HTTPException(status_code=409, detail="Takeoff requires an Office Verified measurement revision")
    template_rev = await db.get(TakeoffTemplateRevision, payload.template_revision_id)
    if not template_rev:
        raise HTTPException(status_code=404, detail="Takeoff template revision not found")
    mset = await db.get(MeasurementSet, measurement.set_id)
    if estimate.property_id and mset and mset.property_id and str(estimate.property_id) != str(mset.property_id):
        raise HTTPException(status_code=409, detail="Measurement revision belongs to a different property")
    return estimate, measurement, template_rev


async def _packaging_for_line(db: AsyncSession, material_id, line_unit: str, calculated_quantity: float, explicit_coverage=None) -> dict:
    """Resolve package/order quantity without hard-coding roofing package assumptions."""
    if explicit_coverage not in (None, "") and float(explicit_coverage) > 0:
        coverage = float(explicit_coverage)
        return {
            "order_quantity": package_quantity(calculated_quantity, coverage_per_package=coverage),
            "coverage_per_package": coverage,
            "coverage_source": "template_rule",
            "package_conversion_factor": None,
            "purchase_unit": None,
        }

    material = await db.get(Material, material_id) if material_id else None
    if material:
        coverage = normalized_product_coverage(material.coverage_amount, material.coverage_unit, line_unit)
        if coverage:
            return {
                "order_quantity": package_quantity(calculated_quantity, coverage_per_package=coverage),
                "coverage_per_package": coverage,
                "coverage_source": "material_catalog",
                "package_conversion_factor": None,
                "purchase_unit": material.purchase_unit,
            }

    sm = None
    if material_id:
        sm = await inv_core.preferred_supplier_material(db, material_id) or await inv_core.best_known_supplier_material(db, material_id)
    conversion = float(sm.conversion_factor or 0) if sm else 0
    if conversion > 0:
        return {
            "order_quantity": package_quantity(calculated_quantity, conversion_factor=conversion),
            "coverage_per_package": None,
            "coverage_source": "supplier_conversion",
            "package_conversion_factor": conversion,
            "purchase_unit": sm.supplier_uom,
        }
    return {
        "order_quantity": None,
        "coverage_per_package": None,
        "coverage_source": None,
        "package_conversion_factor": None,
        "purchase_unit": material.purchase_unit if material else None,
    }


def _scoped_squares(totals: dict) -> float:
    value = totals.get("takeoff_squares")
    if value is None:
        value = totals.get("total_squares", 0)
    return float(value or 0)


async def _previous_waste_change(db: AsyncSession, estimate_id, current_percent: float, current_totals: dict) -> dict | None:
    previous = (await db.execute(select(EstimateTakeoff).where(
        EstimateTakeoff.estimate_id == estimate_id
    ).order_by(EstimateTakeoff.generated_at.desc(), EstimateTakeoff.id.desc()))).scalars().first()
    if not previous:
        return None
    previous_measurement = await db.get(MeasurementRevision, previous.measurement_revision_id)
    if not previous_measurement:
        return None
    previous_out = await measurement_svc.build_out(db, previous_measurement)
    previous_totals = previous_out.get("totals") or {}
    previous_base = resolve_waste_percent(
        previous.company_default_waste_percent,
        template=previous.template_waste_percent,
        estimate=previous.estimate_waste_override,
    )
    previous_overrides = previous.structure_waste_overrides or {}
    previous_percent = weighted_roof_waste_percent(
        previous_totals.get("area_by_structure") or [],
        base_waste=previous_base,
        structure_overrides=previous_overrides,
    ) if previous_overrides else previous_base
    previous_extra = _scoped_squares(previous_totals) * float(previous_percent or 0) / 100.0
    current_extra = _scoped_squares(current_totals) * float(current_percent or 0) / 100.0
    return {
        "previous_percent": round(float(previous_percent or 0), 4),
        "current_percent": round(float(current_percent or 0), 4),
        "percent_delta": round(float(current_percent or 0) - float(previous_percent or 0), 4),
        "previous_extra_squares": round(previous_extra, 4),
        "current_extra_squares": round(current_extra, 4),
        "extra_squares_delta": round(current_extra - previous_extra, 4),
        "previous_takeoff_id": str(previous.id),
    }


async def preview(db: AsyncSession, estimate_id: str, payload) -> dict:
    estimate, measurement, template_rev = await _validated_inputs(db, estimate_id, payload)
    mout = await measurement_svc.build_out(db, measurement)
    totals, summary = mout["totals"], mout.get("summary") or {}
    company_waste = await company_default_waste(db)
    base_waste = resolve_waste_percent(
        company_waste, template=template_rev.default_waste_percent, estimate=payload.estimate_waste_override
    )
    structure_overrides = payload.structure_waste_overrides or {}
    roof_waste = weighted_roof_waste_percent(
        totals.get("area_by_structure") or [], base_waste=base_waste, structure_overrides=structure_overrides
    ) if structure_overrides else base_waste
    rules = (await db.execute(select(TakeoffRule).where(
        TakeoffRule.template_revision_id == template_rev.id
    ).order_by(TakeoffRule.sort))).scalars().all()
    out_lines = []
    for rule in rules:
        raw = metric_value(rule.metric_key, totals, summary, payload.drip_edge_override_lf)
        basis_qty = round(float(raw or 0) * float(rule.quantity_factor or 0), 4)
        if basis_qty == 0:
            continue
        rule_base_waste = resolve_waste_percent(
            company_waste, template=template_rev.default_waste_percent,
            assembly=rule.assembly_waste_percent, estimate=payload.estimate_waste_override,
        )
        roof_metric = rule.metric_key.startswith("roof_squares") or rule.metric_key.startswith("roof_area_sqft")
        effective_rule_waste = weighted_roof_waste_percent(
            totals.get("area_by_structure") or [], base_waste=rule_base_waste,
            structure_overrides=structure_overrides,
        ) if structure_overrides and roof_metric else rule_base_waste
        snap = rule.assembly_snapshot or {}
        for item in snap.get("items") or []:
            measured = round(basis_qty * float(item.get("quantity_factor") or 0), 4)
            is_labor = bool(item.get("is_labor"))
            if item.get("waste_override") is not None:
                waste = float(item["waste_override"])
            elif rule.apply_waste and not is_labor:
                waste = effective_rule_waste
            else:
                waste = 0.0
            calculated = calc.calculated_quantity(measured, waste)
            packaging = await _packaging_for_line(
                db, item.get("material_id"), item.get("unit") or "EA", calculated,
                explicit_coverage=None if is_labor else rule.coverage_per_package,
            ) if not is_labor else {
                "order_quantity": None, "coverage_per_package": None, "coverage_source": None,
                "package_conversion_factor": None, "purchase_unit": None,
            }
            provenance = {
                "rule_id": str(rule.id), "rule_name": rule.name, "metric_key": rule.metric_key,
                "raw_metric_value": raw, "quantity_factor": rule.quantity_factor,
                "measurement_revision_id": str(measurement.id), "measurement_revision_number": measurement.revision_number,
                "template_revision_id": str(template_rev.id), "template_revision_number": template_rev.revision_number,
                "assembly_id": str(rule.assembly_id) if rule.assembly_id else None,
                "assembly_version": rule.assembly_version, "applied_waste_percent": waste,
                "coverage_source": packaging["coverage_source"],
                "coverage_per_package": packaging["coverage_per_package"],
                "package_conversion_factor": packaging["package_conversion_factor"],
            }
            out_lines.append({
                "description": item.get("description") or rule.name,
                "unit": item.get("unit") or "EA",
                "measured_quantity": measured,
                "waste_percent": waste,
                "quantity": calculated,
                "order_quantity": packaging["order_quantity"],
                "purchase_unit": packaging["purchase_unit"],
                "coverage_per_package": packaging["coverage_per_package"],
                "coverage_source": packaging["coverage_source"],
                "package_conversion_factor": packaging["package_conversion_factor"],
                "material_id": item.get("material_id"),
                "line_kind": "labor" if is_labor else ("material" if item.get("material_id") else "custom"),
                "assembly_id": str(rule.assembly_id) if rule.assembly_id else None,
                "assembly_version": rule.assembly_version,
                "assembly_name": rule.assembly_name,
                "takeoff_provenance": provenance,
            })
    ids, modified = await _existing_generated_state(db, estimate.id)
    waste_change = await _previous_waste_change(db, estimate.id, roof_waste, totals)
    return {
        "estimate_id": str(estimate.id),
        "measurement_revision_id": str(measurement.id), "measurement_revision_number": measurement.revision_number,
        "template_revision_id": str(template_rev.id), "template_revision_number": template_rev.revision_number,
        "company_default_waste_percent": company_waste, "template_waste_percent": template_rev.default_waste_percent,
        "effective_roof_waste_percent": roof_waste, "waste_change": waste_change, "lines": out_lines,
        "generated_line_ids_to_replace": ids, "manually_modified_generated_lines": modified,
        "review_required": bool(modified),
    }


async def _snapshot_cost(db: AsyncSession, line: dict) -> None:
    sm = None
    if line.get("material_id"):
        sm = await inv_core.preferred_supplier_material(db, line["material_id"]) or await inv_core.best_known_supplier_material(db, line["material_id"])
    if not sm:
        line.setdefault("material_cost", 0)
        line.setdefault("labor_cost", 0)
        return
    line["supplier_material_id"] = str(sm.id)
    line["material_cost"] = float(sm.current_cost or 0)
    line["base_cost"] = float(sm.current_cost or 0)
    line["conversion_factor"] = sm.conversion_factor
    line["purchase_unit"] = line.get("purchase_unit") or sm.supplier_uom
    line["supplier_item_number"] = sm.supplier_item_number
    line["cost_source"] = sm.price_status or "manual"
    if sm.supplier_id:
        supplier = await db.get(Supplier, sm.supplier_id)
        line["cost_source_supplier_id"] = str(sm.supplier_id)
        line["cost_source_supplier_name"] = supplier.name if supplier else None


async def apply(db: AsyncSession, estimate_id: str, payload, user) -> dict:
    estimate, measurement, template_rev = await _validated_inputs(db, estimate_id, payload)
    p = await preview(db, estimate_id, payload)
    if p["review_required"] and not payload.replace_modified_generated:
        raise HTTPException(status_code=409, detail={
            "code": "TAKEOFF_GENERATED_LINES_MODIFIED",
            "message": "Generated takeoff lines were manually edited. Review them before replacing.",
            "lines": p["manually_modified_generated_lines"],
        })
    old_ids = p["generated_line_ids_to_replace"]
    if old_ids:
        await db.execute(delete(EstimateLineItem).where(EstimateLineItem.id.in_(old_ids)))
        await db.flush()

    takeoff = EstimateTakeoff(
        estimate_id=estimate.id, measurement_revision_id=measurement.id, template_revision_id=template_rev.id,
        measurement_revision_number=measurement.revision_number, template_revision_number=template_rev.revision_number,
        company_default_waste_percent=p["company_default_waste_percent"], template_waste_percent=template_rev.default_waste_percent,
        estimate_waste_override=payload.estimate_waste_override,
        structure_waste_overrides=payload.structure_waste_overrides or {}, drip_edge_override_lf=payload.drip_edge_override_lf,
        generated_by=getattr(user, "email", None), generated_at=datetime.now(timezone.utc),
    )
    db.add(takeoff)
    await db.flush()

    start_sort = (await db.execute(select(EstimateLineItem.sort).where(
        EstimateLineItem.estimate_id == estimate.id
    ).order_by(EstimateLineItem.sort.desc()))).scalars().first()
    sort = int(start_sort or -1) + 1
    created = []
    for raw in p["lines"]:
        line = dict(raw)
        provenance = line.pop("takeoff_provenance")
        if line.get("line_kind") == "labor":
            line["labor_cost"] = 0
            line["material_cost"] = 0
        else:
            await _snapshot_cost(db, line)
        if estimate.price_book_id and (line.get("material_id") or line.get("assembly_id")):
            price_rule = await pricing_svc.find_rule(db, estimate.price_book_id, line.get("material_id"), line.get("assembly_id"))
            if price_rule:
                ucost = calc.unit_cost(line.get("material_cost"), line.get("labor_cost"), line.get("equipment_cost"), line.get("subcontract_cost"))
                priced = pricing_svc.apply_rule(price_rule, ucost)
                if priced is not None:
                    line["selling_unit_price"] = priced
        calc.compute_line(line)
        dbline = EstimateLineItem(
            estimate_id=estimate.id, description=line.get("description") or "", quantity=line["quantity"],
            unit=line.get("unit") or "EA", unit_price=line["unit_price"], line_total=line["line_total"], sort=sort,
            material_id=line.get("material_id") or None, supplier_material_id=line.get("supplier_material_id") or None,
            line_kind=line.get("line_kind") or "custom", base_cost=line.get("base_cost") or 0,
            material_cost=line.get("material_cost") or 0, labor_cost=line.get("labor_cost") or 0,
            equipment_cost=line.get("equipment_cost") or 0, subcontract_cost=line.get("subcontract_cost") or 0,
            measured_quantity=line.get("measured_quantity") or 0, waste_percent=line.get("waste_percent") or 0,
            order_quantity=line.get("order_quantity"), purchase_unit=line.get("purchase_unit"),
            conversion_factor=line.get("conversion_factor"), markup_percent=line.get("markup_percent") or 0,
            selling_unit_price=line.get("selling_unit_price") or 0,
            cost_source_supplier_id=line.get("cost_source_supplier_id") or None,
            cost_source_supplier_name=line.get("cost_source_supplier_name"), supplier_item_number=line.get("supplier_item_number"),
            cost_source=line.get("cost_source"), cost_snapshot_at=datetime.now(timezone.utc) if line.get("material_id") else None,
            assembly_id=line.get("assembly_id") or None, assembly_version=line.get("assembly_version"), assembly_name=line.get("assembly_name"),
        )
        db.add(dbline)
        await db.flush()
        provenance["order_quantity"] = dbline.order_quantity
        provenance["purchase_unit"] = dbline.purchase_unit
        provenance["generated_line_snapshot"] = _line_signature(dbline)
        db.add(EstimateTakeoffLine(
            takeoff_id=takeoff.id, estimate_line_item_id=dbline.id, rule_id=provenance.get("rule_id"),
            metric_key=provenance["metric_key"], raw_metric_value=provenance["raw_metric_value"],
            measured_quantity=dbline.measured_quantity, applied_waste_percent=dbline.waste_percent,
            calculated_quantity=dbline.quantity, order_quantity=dbline.order_quantity, provenance=provenance,
        ))
        created.append(str(dbline.id))
        sort += 1

    all_lines = (await db.execute(select(EstimateLineItem).where(EstimateLineItem.estimate_id == estimate.id))).scalars().all()
    summary = calc.summarize([{
        "quantity": x.quantity, "material_cost": x.material_cost, "labor_cost": x.labor_cost,
        "equipment_cost": x.equipment_cost, "subcontract_cost": x.subcontract_cost,
        "line_total": x.line_total,
        "_unit_cost": calc.unit_cost(x.material_cost, x.labor_cost, x.equipment_cost, x.subcontract_cost),
    } for x in all_lines], estimate.tax_rate)
    estimate.subtotal, estimate.tax, estimate.total = summary["subtotal"], summary["tax"], summary["total"]
    estimate.version += 1
    await db.flush()
    return {**p, "takeoff_id": str(takeoff.id), "created_line_ids": created, "estimate_version": estimate.version}


def _metric_map(out: dict) -> dict:
    totals, summary = out.get("totals") or {}, out.get("summary") or {}
    edges = totals.get("takeoff_edge_totals")
    if edges is None:
        edges = totals.get("edge_totals") or {}
    roof_area = totals.get("takeoff_area_sqft")
    roof_squares = totals.get("takeoff_squares")
    pitch_rows = totals.get("takeoff_area_by_pitch")
    if roof_area is None:
        roof_area = totals.get("total_area_sqft", 0)
    if roof_squares is None:
        roof_squares = totals.get("total_squares", 0)
    if pitch_rows is None:
        pitch_rows = totals.get("area_by_pitch") or []
    return {
        "roof_area_sqft": roof_area, "roof_squares": roof_squares,
        "predominant_pitch": totals.get("takeoff_predominant_pitch", totals.get("predominant_pitch")),
        "area_by_pitch": pitch_rows, "area_by_structure": totals.get("area_by_structure") or [],
        **edges,
        "penetration_counts": totals.get("takeoff_penetration_counts", totals.get("penetration_counts") or {}),
        "existing_layers": summary.get("existing_layers"), "existing_condition": summary.get("existing_condition"),
        "drip_edge_lf": summary.get("drip_edge_lf"), "damaged_deck_sf": summary.get("damaged_deck_sf"),
        "replacement_sheets": summary.get("replacement_sheets"), "stories": totals.get("max_stories", summary.get("stories")),
        "height_ft": totals.get("max_height_ft"), "steep_access": summary.get("steep_access"),
        "high_access": summary.get("high_access"), "long_carry": summary.get("long_carry"),
        "restricted_access": summary.get("restricted_access"),
    }


async def status(db: AsyncSession, estimate_id: str) -> dict:
    estimate = await db.get(Estimate, estimate_id)
    if not estimate:
        raise HTTPException(status_code=404, detail="Estimate not found")
    takeoff = (await db.execute(select(EstimateTakeoff).where(
        EstimateTakeoff.estimate_id == estimate.id
    ).order_by(EstimateTakeoff.generated_at.desc()))).scalars().first()
    if not takeoff:
        return {"estimate_id": str(estimate.id), "has_takeoff": False, "measurements_changed": False, "changed_metrics": []}
    used = await db.get(MeasurementRevision, takeoff.measurement_revision_id)
    latest = None
    if used:
        latest = (await db.execute(select(MeasurementRevision).where(
            MeasurementRevision.set_id == used.set_id
        ).order_by(MeasurementRevision.revision_number.desc()))).scalars().first()
    changed = bool(latest and str(latest.id) != str(used.id))
    changes = []
    if changed and used and latest:
        before = _metric_map(await measurement_svc.build_out(db, used))
        after = _metric_map(await measurement_svc.build_out(db, latest))
        for key in before.keys() | after.keys():
            if before.get(key) != after.get(key):
                changes.append({"metric": key, "from": before.get(key), "to": after.get(key)})
    return {
        "estimate_id": str(estimate.id), "has_takeoff": True, "takeoff_id": str(takeoff.id),
        "measurement_revision_id": str(takeoff.measurement_revision_id), "measurement_revision_number": takeoff.measurement_revision_number,
        "template_revision_id": str(takeoff.template_revision_id), "template_revision_number": takeoff.template_revision_number,
        "latest_measurement_revision_id": str(latest.id) if latest else None,
        "latest_measurement_revision_number": latest.revision_number if latest else None,
        "measurements_changed": changed, "changed_metrics": changes,
    }


async def lock_measurement_for_accepted_estimate(db: AsyncSession, estimate_id, actor_email: str | None = None) -> MeasurementRevision | None:
    takeoff = (await db.execute(select(EstimateTakeoff).where(
        EstimateTakeoff.estimate_id == estimate_id
    ).order_by(EstimateTakeoff.generated_at.desc()))).scalars().first()
    if not takeoff:
        return None
    rev = await db.get(MeasurementRevision, takeoff.measurement_revision_id)
    if rev and not rev.is_immutable:
        rev.is_immutable = True
        rev.status = "locked"
        rev.locked_by = actor_email
        rev.locked_at = datetime.now(timezone.utc)
        rev.updated_at = datetime.now(timezone.utc)
        await db.flush()
    return rev
