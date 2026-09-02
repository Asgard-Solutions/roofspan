"use strict";
// Phase C — Field Roof Sketch Measurement Reconciliation (pure, Node-testable; NO React/RN).
//
// Geometry/calculation is NEVER re-implemented here — all Confirmed/Proposed/Difference numbers,
// scale-suppression and Measured-&-Locked discrepancies come verbatim from the shared canonical engine
// (@roofspan/roof-sketch-core deriveProposals). This module only adds Field decision provenance +
// truthful status + the measurement-update body assembly that routes Accept through RoofSpan's EXISTING
// Field measurement workflow (measurement_update:<revisionId>). The Measurement Revision stays the sole
// authority: "Accept Proposed" is only a PENDING intent until the authoritative revision actually holds
// the proposed value.
const RS = require("@roofspan/roof-sketch-core");
const { edgeForEdit, edgeToBody } = require("./measurementEdges");

const PENDING = "pending_accept";
const ACCEPTED = "accepted";
const KEEP = "keep_current";

// Same tolerances Office uses (frontend proposalLifecycle) so Field/Office promote identically.
const TOL = { area_sqft: 0.5, length_ft: 0.05, pitch_rise: 0.01 };
function valuesMatch(metric, a, b) {
  if (a == null || b == null) return false;
  const tol = TOL[metric] != null ? TOL[metric] : 0.01;
  return Math.abs(Number(a) - Number(b)) <= tol;
}

// The authoritative relational measurement id a sketch facet/edge is EXPLICITLY linked to (never
// inferred from label/length/type/order). Returns null when the sketch element carries no mapping.
function relationalIdForRecord(doc, rec) {
  if (rec.target_type === "facet") {
    const f = (doc.facets || []).find((x) => x.id === rec.target_id);
    return f && f.measurement_facet_id != null ? String(f.measurement_facet_id) : null;
  }
  if (rec.target_type === "edge") {
    const e = (doc.edges || []).find((x) => x.id === rec.target_id);
    return e && e.measurement_edge_id != null ? String(e.measurement_edge_id) : null;
  }
  return null;
}

// The set of measurement facet/edge ids that belong to THIS structure only (structure isolation). An
// edge belongs to the structure iff its facet belongs to it. A mapping pointing outside this set is
// invalid and must block acceptance — never silently re-pointed.
function scopedMeasurementIds(detail, structureId) {
  const facetIds = new Set();
  const edgeIds = new Set();
  const facets = (detail && detail.facets) || [];
  const edges = (detail && detail.edges) || [];
  for (const f of facets) {
    if (String(f.structure_id) === String(structureId)) facetIds.add(String(f.id));
  }
  for (const e of edges) {
    if (e.facet_id != null && facetIds.has(String(e.facet_id))) edgeIds.add(String(e.id));
  }
  return { facetIds, edgeIds };
}

function isMappingValid(relationalId, validIdSet) {
  return relationalId != null && validIdSet.has(String(relationalId));
}

// Find the persisted decision for a proposal. Prefer the relational key (how Accept stores it); fall
// back to the sketch-id key (unmapped Keep Current provenance).
function decisionForProposal(doc, rec, relationalId) {
  const decs = doc.proposal_decisions || [];
  if (relationalId != null) {
    const r = decs.find((x) => x.target_type === rec.target_type && String(x.target_id) === String(relationalId) && x.metric === rec.metric);
    if (r) return r;
  }
  return decs.find((x) => x.target_type === rec.target_type && String(x.target_id) === String(rec.target_id) && x.metric === rec.metric) || null;
}

// The value currently persisted in the authoritative Measurement Revision for a mapped target.
function persistedMeasurementValue(detail, targetType, relationalId, metric) {
  if (relationalId == null || !detail) return null;
  if (targetType === "facet" && metric === "area_sqft") {
    const f = (detail.facets || []).find((x) => String(x.id) === String(relationalId));
    return f ? Number(f.area_sqft) : null;
  }
  if (targetType === "edge" && metric === "length_ft") {
    const e = (detail.edges || []).find((x) => String(x.id) === String(relationalId));
    return e ? Number(e.length_ft) : null;
  }
  return null;
}

// A pending acceptance may be promoted to ACCEPTED only when the AUTHORITATIVE persisted value matches
// the proposed value AND the measurement-update mutation is no longer in a non-final state. A missing
// mutation (null) means "not pending" — the value is already what it should be.
function _mutationSettled(state) {
  return state !== "pending" && state !== "failed" && state !== "conflict" && state !== "locked";
}
function shouldPromote(decision, persisted, mutationState) {
  return !!decision && decision.decision === PENDING
    && valuesMatch(decision.metric, persisted, decision.proposed_value != null ? decision.proposed_value : decision.value)
    && _mutationSettled(mutationState);
}

// Truthful display status for a proposal decision. Never reports Accepted until the authoritative value
// matches and the mutation settled; a settled-but-mismatched value is Review required, not accepted.
function deriveStatus({ decision, mutationState, persisted, metric }) {
  if (!decision) return null;
  if (decision.decision === KEEP) return "Kept current";
  if (decision.decision === ACCEPTED) return "Accepted / Synced";
  if (decision.decision === PENDING) {
    const proposed = decision.proposed_value != null ? decision.proposed_value : decision.value;
    if (shouldPromote(decision, persisted, mutationState)) return "Accepted / Synced";
    if (!_mutationSettled(mutationState) || persisted == null) return "Pending sync";
    return "Review required"; // settled but the server holds a different value — do not guess
  }
  return null;
}

// Build the Field reconciliation rows for the open structure. Consumes ONLY the shared engine's records
// + the durable sketch decisions + the scoped measurement detail. Proposals remain VISIBLE even when
// editing is blocked (locked revision / conflict), but no action is offered in that state.
function buildFieldProposals({ doc, measurementDetail, structureId, editingBlocked = false, measurementMutationState = null } = {}) {
  const records = RS.deriveProposals(doc);
  const { facetIds, edgeIds } = scopedMeasurementIds(measurementDetail, structureId);
  const rows = [];
  for (const rec of records) {
    if (rec.code === "scale_unresolved") {
      rows.push({ kind: "calibrate", code: rec.code, message: "Calibrate the roof before dimensional measurements can be proposed.", canAccept: false, canKeep: false });
      continue;
    }
    if (rec.code === "locked_edge_discrepancy") {
      rows.push({
        kind: "measured_locked", code: rec.code, target_type: "edge", metric: rec.metric, unit: "LF",
        label: rec.target_id, confirmed: rec.confirmed, proposed: rec.proposed, difference: rec.difference,
        message: "Measured & Locked — physically measured; drawn geometry differs. The measured value is kept.",
        canAccept: false, canKeep: false,
      });
      continue;
    }
    const relationalId = relationalIdForRecord(doc, rec);
    const validSet = rec.target_type === "facet" ? facetIds : edgeIds;
    const mapped = isMappingValid(relationalId, validSet);
    const decision = decisionForProposal(doc, rec, relationalId);
    const persisted = persistedMeasurementValue(measurementDetail, rec.target_type, relationalId, rec.metric);
    rows.push({
      kind: mapped ? "proposal" : "unmapped",
      code: rec.code, target_type: rec.target_type, sketch_id: rec.target_id, relational_id: relationalId,
      metric: rec.metric, unit: rec.metric === "area_sqft" ? "SF" : "LF",
      label: rec.label || rec.target_id, confirmed: rec.confirmed, proposed: rec.proposed, difference: rec.difference,
      mapped, decision: decision ? decision.decision : null,
      status: deriveStatus({ decision, mutationState: measurementMutationState, persisted, metric: rec.metric }),
      canAccept: mapped && !editingBlocked && rec.proposed != null,   // never Accept an unmapped/uncalibrated/blocked proposal
      canKeep: !editingBlocked,
      reviewMessage: mapped ? null : "Review required — this sketch element isn't matched to a measurement record.",
    });
  }
  return rows;
}

// Record an explicit ACCEPT as a durable pending_accept decision on the sketch document (keyed by the
// relational measurement id, mirroring Office). Pure — the screen commits the returned doc.
function acceptProposalDecision(doc, rec, relationalId, proposedValue) {
  return RS.setProposalDecision(doc, { targetType: rec.target_type, targetId: relationalId, metric: rec.metric, decision: PENDING, value: proposedValue });
}

// Record KEEP CURRENT provenance (no measurement change). Keyed by relational id when mapped, else the
// sketch id (unmapped provenance).
function keepCurrentDecision(doc, rec, targetId) {
  return RS.setProposalDecision(doc, { targetType: rec.target_type, targetId, metric: rec.metric, decision: KEEP, value: null });
}

// ---- authoritative measurement-update assembly (SAFEGUARD) --------------------------------------
// Faithful detail -> update body, mirroring the Field Measurements screen (edgeForEdit/edgeToBody +
// the same facet/structure/penetration/summary mapping) so identities and ALL unrelated fields survive.
function detailToUpdateBody(detail) {
  const d = detail || {};
  return {
    source: d.source || "field",
    mark_field_complete: false,
    structures: (d.structures || []).map((st, i) => ({
      ref: st.id || st.ref, name: st.name || "", structure_type: st.structure_type || "main_house",
      included_in_scope: st.included_in_scope !== false,
      stories: st.stories != null ? st.stories : null, approx_height_ft: st.approx_height_ft != null ? st.approx_height_ft : null,
      attachment: st.attachment || null, notes: st.notes || null, sort: i,
    })),
    facets: (d.facets || []).map((f, i) => ({
      ref: f.id || f.ref, structure_ref: f.structure_id || f.structure_ref || null, facet_label: f.facet_label || `F${i + 1}`,
      pitch_rise: f.pitch_rise != null ? f.pitch_rise : null, area_sqft: Number(f.area_sqft) || 0,
      width_ft: f.width_ft != null ? f.width_ft : null, length_ft: f.length_ft != null ? f.length_ft : null,
      roof_material: f.roof_material || null, notes: f.notes || null, sort: i,
    })),
    edges: (d.edges || []).map((e, i) => edgeToBody(edgeForEdit(e), i)),
    penetrations: (d.penetrations || []).map((p, i) => ({
      ref: p.id || p.ref, pen_type: p.pen_type, quantity: parseInt(p.quantity, 10) || 1, facet_ref: p.facet_id || p.facet_ref || null,
      diameter_in: p.diameter_in != null ? p.diameter_in : null, width_in: p.width_in != null ? p.width_in : null,
      length_in: p.length_in != null ? p.length_in : null, notes: p.notes || null, sort: i,
    })),
    summary: d.summary || {},
  };
}

// Apply ONLY the mapped value onto the NEWEST durable revision detail, preserving every other structure,
// facet, edge, penetration and summary field. Returns the next detail (for the optimistic cache) plus the
// coalescing measurement_update body + If-Match token. Idempotent: re-accepting sets the same value.
function buildAcceptedMeasurementUpdate(currentDetail, { targetType, relationalId, metric, proposedValue } = {}) {
  const next = JSON.parse(JSON.stringify(currentDetail || {}));
  let changed = false;
  if (targetType === "facet" && metric === "area_sqft") {
    (next.facets || []).forEach((f) => { if (String(f.id) === String(relationalId)) { f.area_sqft = Number(proposedValue); changed = true; } });
  } else if (targetType === "edge" && metric === "length_ft") {
    (next.edges || []).forEach((e) => { if (String(e.id) === String(relationalId)) { e.length_ft = Number(proposedValue); changed = true; } });
  }
  return { nextDetail: next, body: detailToUpdateBody(next), ifMatch: currentDetail ? currentDetail.updated_at : null, changed };
}

// Promote pending_accept -> accepted ONLY where the authoritative persisted revision value matches the
// proposed value and the measurement mutation settled. Returns { doc, promoted, changed }. Never demotes
// or guesses. Consumed by the screen on refresh/reopen so a truthful state survives interruption.
function finalizeDecisions(doc, { measurementDetail, measurementMutationState } = {}) {
  const decs = doc.proposal_decisions || [];
  let changed = false;
  const promoted = [];
  const next = decs.map((dec) => {
    if (dec.decision !== PENDING) return dec;
    const persisted = persistedMeasurementValue(measurementDetail, dec.target_type, dec.target_id, dec.metric);
    if (shouldPromote(dec, persisted, measurementMutationState)) {
      changed = true;
      promoted.push(`${dec.target_type}::${dec.target_id}::${dec.metric}`);
      return { ...dec, decision: ACCEPTED, accepted_value: persisted, finalized_at: new Date().toISOString() };
    }
    return dec;
  });
  return { doc: changed ? RS.setDecisions(doc, next) : doc, promoted, changed };
}

module.exports = {
  PENDING, ACCEPTED, KEEP, valuesMatch,
  relationalIdForRecord, scopedMeasurementIds, isMappingValid, decisionForProposal, persistedMeasurementValue,
  shouldPromote, deriveStatus, buildFieldProposals,
  acceptProposalDecision, keepCurrentDecision,
  detailToUpdateBody, buildAcceptedMeasurementUpdate, finalizeDecisions,
};
