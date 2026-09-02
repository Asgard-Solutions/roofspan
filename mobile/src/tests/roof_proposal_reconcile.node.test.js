"use strict";
// Phase C contracts: Field Roof Sketch Measurement Reconciliation. Uses the SHARED engine
// (RS.deriveProposals) for all numbers + the pure Field reconcile layer for provenance/status/measurement
// assembly. NO React/RN. Proves: explicit-mapping-only, structure isolation, scale suppression,
// Confirmed/Proposed/Difference, Measured-&-Locked, Accept->pending->accepted/mismatch, Keep Current,
// offline durability + reopen, idempotency, measurement-update preservation of unrelated fields, and the
// revision-lock / conflict gating (B3D respected).
const assert = require("assert");
const RS = require("@roofspan/roof-sketch-core");
const R = require("../roofProposalReconcile");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// A calibrated square facet (10x8 model units, 1 ft/unit, flat) mapped to measurement facet MF1, plus a
// mapped eave edge, on structure ST1.
function baseDoc() {
  const d = RS.createSketchDocument({ structureId: "ST1" });
  d.scale = RS.calibrateScale({ canvasDistance: 10, realFeet: 10, method: "structure_calibration" }); // 1 ft/unit
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 }];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2", type: "eave", measurement_edge_id: "ME1", confirmed_length_ft: 9.5 },
    { id: "e2", v1: "v2", v2: "v3", type: "rake" },
    { id: "e3", v1: "v3", v2: "v4", type: "eave" },
    { id: "e4", v1: "v4", v2: "v1", type: "rake" },
  ];
  d.facets = [{ id: "f1", edgeIds: ["e1", "e2", "e3", "e4"], vertexIds: [], pitch_rise: 0, label: "F1", measurement_facet_id: "MF1", confirmed_area_sqft: 70 }];
  return RS.normalizeSketchDocument(d);
}
// Measurement detail with MF1 (structure ST1), ME1 on MF1, plus UNRELATED facet MF2 on another structure.
function detail() {
  return {
    id: "REV1", updated_at: "2026-06-01T00:00:00Z", source: "field", revision_number: 1,
    structures: [{ id: "ST1", name: "Main House", structure_type: "main_house", included_in_scope: true }, { id: "ST2", name: "Detached Garage", structure_type: "detached_garage" }],
    facets: [
      { id: "MF1", structure_id: "ST1", facet_label: "F1", pitch_rise: 0, area_sqft: 70, width_ft: 10, length_ft: 8, roof_material: "shingle" },
      { id: "MF2", structure_id: "ST2", facet_label: "G1", pitch_rise: 6, area_sqft: 300 },
    ],
    edges: [
      { id: "ME1", edge_type: "eave", length_ft: 9.5, facet_id: "MF1", label: "E1" },
      { id: "ME9", edge_type: "eave", length_ft: 20, facet_id: "MF2" },
    ],
    penetrations: [{ id: "MP1", pen_type: "pipe_boot", quantity: 3, facet_id: "MF1" }],
    summary: { existing_covering_type: "architectural shingle", deck_type: "OSB" },
  };
}
const rowFor = (rows, tt, sketchId, metric) => rows.find((r) => r.target_type === tt && r.sketch_id === sketchId && r.metric === metric);

// ---- 1. Confirmed / Proposed / Difference (calibrated) ----
{
  const rows = R.buildFieldProposals({ doc: baseDoc(), measurementDetail: detail(), structureId: "ST1" });
  const fa = rowFor(rows, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.confirmed, 70);
  assert.strictEqual(fa.proposed, 80);              // 10*8 = 80 SF flat
  assert.strictEqual(fa.difference, 10);
  assert.strictEqual(fa.unit, "SF"); assert.strictEqual(fa.mapped, true); assert.strictEqual(fa.canAccept, true);
  const ea = rowFor(rows, "edge", "e1", "length_ft");
  assert.strictEqual(ea.confirmed, 9.5); assert.strictEqual(ea.proposed, 10); assert.strictEqual(ea.difference, 0.5);
  assert.strictEqual(ea.unit, "LF"); assert.strictEqual(ea.mapped, true); assert.strictEqual(ea.canAccept, true);
  ok("calibrated facet/edge show correct Confirmed, Proposed, Difference (SF/LF) and are acceptable when mapped");
}

// ---- 2. scale suppression: uncalibrated sketch produces NO dimensional proposal, only a Calibrate notice ----
{
  const d = baseDoc(); d.scale = { resolved: false, feetPerUnit: null };
  const rows = R.buildFieldProposals({ doc: RS.normalizeSketchDocument(d), measurementDetail: detail(), structureId: "ST1" });
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].kind, "calibrate");
  assert.ok(/[Cc]alibrate/.test(rows[0].message));
  assert.strictEqual(rows.some((r) => r.metric === "area_sqft" || r.metric === "length_ft"), false, "no SF/LF proposals while uncalibrated");
  ok("uncalibrated sketch suppresses all dimensional proposals and shows only a Calibrate notice");
}

// ---- 3. explicit mapping only: an UNMAPPED facet cannot be accepted (Review required) ----
{
  const d = baseDoc(); d.facets[0].measurement_facet_id = null;   // unmap
  const rows = R.buildFieldProposals({ doc: RS.normalizeSketchDocument(d), measurementDetail: detail(), structureId: "ST1" });
  const fa = rowFor(rows, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.mapped, false); assert.strictEqual(fa.canAccept, false); assert.strictEqual(fa.kind, "unmapped");
  assert.ok(/Review required/.test(fa.reviewMessage));
  ok("an unmapped facet is Review required and can never be accepted (mapping is explicit, never inferred)");
}

// ---- 4. stale mapping (points at a non-existent / wrong-scope id) blocks acceptance ----
{
  const d = baseDoc(); d.facets[0].measurement_facet_id = "GHOST";
  const rows = R.buildFieldProposals({ doc: RS.normalizeSketchDocument(d), measurementDetail: detail(), structureId: "ST1" });
  const fa = rowFor(rows, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.mapped, false); assert.strictEqual(fa.canAccept, false);
  ok("a stale/missing mapping is treated as unmapped and blocks Accept (never silently re-pointed)");
}

// ---- 5. STRUCTURE ISOLATION: a Main-House sketch facet mapped to a Detached-Garage measurement facet is invalid ----
{
  const d = baseDoc(); d.facets[0].measurement_facet_id = "MF2";   // MF2 belongs to ST2, not ST1
  const rows = R.buildFieldProposals({ doc: RS.normalizeSketchDocument(d), measurementDetail: detail(), structureId: "ST1" });
  const fa = rowFor(rows, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.mapped, false, "cross-structure mapping is not valid for THIS structure");
  assert.strictEqual(fa.canAccept, false);
  // and the update assembly, if ever attempted, would target MF2 — but canAccept=false prevents it.
  ok("structure isolation: a Main House facet can never accept-update a Detached Garage measurement facet");
}

// ---- 6. Measured & Locked edge shows a discrepancy and is NOT acceptable ----
{
  const d = baseDoc();
  d.edges[0].locked = true; d.edges[0].confirmed_length_ft = 42.0;   // measured & locked, geometry ~10
  const rows = R.buildFieldProposals({ doc: RS.normalizeSketchDocument(d), measurementDetail: detail(), structureId: "ST1" });
  const ml = rows.find((r) => r.kind === "measured_locked");
  assert.ok(ml, "a measured-&-locked edge yields a discrepancy row");
  assert.strictEqual(ml.confirmed, 42.0); assert.strictEqual(ml.canAccept, false);
  assert.ok(/Measured & Locked/.test(ml.message));
  // there is NO ordinary edge_length proposal for the locked edge (geometry cannot silently overwrite it)
  assert.strictEqual(rows.some((r) => r.kind === "proposal" && r.target_type === "edge" && r.sketch_id === "e1"), false);
  ok("Measured & Locked edge: discrepancy shown, no overwrite proposal, cannot be accepted");
}

// ---- 7. ACCEPT: records pending_accept (durable in the doc) + assembles a measurement_update that changes ONLY the mapped value ----
{
  const doc = baseDoc();
  const fa = rowFor(R.buildFieldProposals({ doc, measurementDetail: detail(), structureId: "ST1" }), "facet", "f1", "area_sqft");
  const doc2 = R.acceptProposalDecision(doc, { target_type: "facet", metric: "area_sqft", target_id: "f1" }, fa.relational_id, fa.proposed);
  const dec = (doc2.proposal_decisions || []).find((x) => x.target_id === "MF1" && x.metric === "area_sqft");
  assert.strictEqual(dec.decision, R.PENDING); assert.strictEqual(dec.proposed_value, 80);
  const upd = R.buildAcceptedMeasurementUpdate(detail(), { targetType: "facet", relationalId: "MF1", metric: "area_sqft", proposedValue: 80 });
  assert.strictEqual(upd.changed, true);
  assert.strictEqual(upd.body.facets.find((f) => f.ref === "MF1").area_sqft, 80, "mapped facet area updated to 80");
  // SAFEGUARD: unrelated records preserved
  assert.strictEqual(upd.body.facets.find((f) => f.ref === "MF2").area_sqft, 300, "unrelated garage facet untouched");
  assert.strictEqual(upd.body.edges.find((e) => e.ref === "ME1").length_ft, 9.5, "unrelated edge untouched");
  assert.strictEqual(upd.body.penetrations.length, 1, "penetrations preserved");
  assert.strictEqual(upd.body.summary.deck_type, "OSB", "summary preserved");
  assert.strictEqual(upd.ifMatch, "2026-06-01T00:00:00Z", "If-Match carries the current revision token");
  ok("Accept -> durable pending_accept + measurement_update changes ONLY the mapped value, preserving all unrelated fields + If-Match");
}

// ---- 8. status lifecycle: pending -> Pending sync; server match -> Accepted; server mismatch -> Review required ----
{
  let doc = R.acceptProposalDecision(baseDoc(), { target_type: "facet", metric: "area_sqft", target_id: "f1" }, "MF1", 80);
  const mkDetail = (area) => { const d = detail(); d.facets.find((f) => f.id === "MF1").area_sqft = area; return d; };
  // mutation still pending -> Pending sync
  let rows = R.buildFieldProposals({ doc, measurementDetail: mkDetail(70), structureId: "ST1", measurementMutationState: "pending" });
  assert.strictEqual(rowFor(rows, "facet", "f1", "area_sqft").status, "Pending sync");
  // mutation settled + server matches 80 -> Accepted / Synced
  rows = R.buildFieldProposals({ doc, measurementDetail: mkDetail(80), structureId: "ST1", measurementMutationState: "synced" });
  assert.strictEqual(rowFor(rows, "facet", "f1", "area_sqft").status, "Accepted / Synced");
  // mutation settled + server holds a DIFFERENT value -> Review required (never falsely accepted)
  rows = R.buildFieldProposals({ doc, measurementDetail: mkDetail(73), structureId: "ST1", measurementMutationState: "synced" });
  assert.strictEqual(rowFor(rows, "facet", "f1", "area_sqft").status, "Review required");
  ok("Accept status is truthful: Pending sync -> Accepted only on authoritative match -> Review required on server mismatch");
}

// ---- 9. finalize promotes pending -> accepted ONLY on authoritative match (durable), idempotent ----
{
  const doc = R.acceptProposalDecision(baseDoc(), { target_type: "facet", metric: "area_sqft", target_id: "f1" }, "MF1", 80);
  const matched = detail(); matched.facets.find((f) => f.id === "MF1").area_sqft = 80;
  const f1 = R.finalizeDecisions(doc, { measurementDetail: matched, measurementMutationState: "synced" });
  assert.strictEqual(f1.changed, true); assert.strictEqual(f1.promoted.length, 1);
  const dec = f1.doc.proposal_decisions.find((x) => x.target_id === "MF1");
  assert.strictEqual(dec.decision, R.ACCEPTED); assert.strictEqual(dec.accepted_value, 80);
  // finalize again -> no further change (idempotent, no loop)
  const f2 = R.finalizeDecisions(f1.doc, { measurementDetail: matched, measurementMutationState: "synced" });
  assert.strictEqual(f2.changed, false);
  // mismatch never promotes
  const mism = detail(); mism.facets.find((f) => f.id === "MF1").area_sqft = 71;
  const f3 = R.finalizeDecisions(doc, { measurementDetail: mism, measurementMutationState: "synced" });
  assert.strictEqual(f3.changed, false, "server mismatch is never promoted to accepted");
  ok("finalize promotes pending->accepted only on authoritative match; idempotent; mismatch never promoted");
}

// ---- 10. KEEP CURRENT: records provenance, NO measurement change, survives reopen ----
{
  const doc = baseDoc();
  const doc2 = R.keepCurrentDecision(doc, { target_type: "facet", metric: "area_sqft", target_id: "f1" }, "MF1");
  const dec = doc2.proposal_decisions.find((x) => x.target_id === "MF1" && x.metric === "area_sqft");
  assert.strictEqual(dec.decision, R.KEEP);
  // reopen: the row reflects Kept current, confirmed value unchanged, proposed still shown for reference
  const rows = R.buildFieldProposals({ doc: doc2, measurementDetail: detail(), structureId: "ST1" });
  const fa = rowFor(rows, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.status, "Kept current"); assert.strictEqual(fa.confirmed, 70); assert.strictEqual(fa.proposed, 80);
  ok("Keep Current records provenance only (no measurement change) and the decision survives reopen");
}

// ---- 11. repeated Accept is idempotent (single decision, same value; coalescing update body) ----
{
  let doc = baseDoc();
  doc = R.acceptProposalDecision(doc, { target_type: "facet", metric: "area_sqft", target_id: "f1" }, "MF1", 80);
  doc = R.acceptProposalDecision(doc, { target_type: "facet", metric: "area_sqft", target_id: "f1" }, "MF1", 80);
  const decs = doc.proposal_decisions.filter((x) => x.target_id === "MF1" && x.metric === "area_sqft");
  assert.strictEqual(decs.length, 1, "one decision only (no duplicates/stale)");
  const u1 = R.buildAcceptedMeasurementUpdate(detail(), { targetType: "facet", relationalId: "MF1", metric: "area_sqft", proposedValue: 80 });
  const u2 = R.buildAcceptedMeasurementUpdate(u1.nextDetail, { targetType: "facet", relationalId: "MF1", metric: "area_sqft", proposedValue: 80 });
  assert.strictEqual(u2.body.facets.find((f) => f.ref === "MF1").area_sqft, 80);
  ok("repeated Accept is idempotent: a single decision, same authoritative value, no stale duplicates");
}

// ---- 12. B3D gating: a LOCKED revision (or conflict) keeps proposals visible but offers NO actions ----
{
  const doc = baseDoc();
  const locked = R.buildFieldProposals({ doc, measurementDetail: detail(), structureId: "ST1", editingBlocked: true });
  const fa = rowFor(locked, "facet", "f1", "area_sqft");
  assert.strictEqual(fa.confirmed, 70); assert.strictEqual(fa.proposed, 80, "values still visible for reference");
  assert.strictEqual(fa.canAccept, false, "no Accept against a locked/conflicted revision");
  assert.strictEqual(fa.canKeep, false, "no Keep Current mutation against a locked/conflicted revision");
  ok("locked revision / sketch conflict: proposals remain visible but Accept + Keep Current are both disabled (B3D respected)");
}

console.log("\nFIELD ROOF SKETCH MEASUREMENT RECONCILIATION (Phase C): all " + n + " assertions passed");
