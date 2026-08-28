"use strict";
// Deterministic proposal generation. Geometry proposes; it never silently overwrites confirmed or
// locked measurements. Unresolved scale => no dimensional proposals at all.
const { distance, polygonArea, pitchAdjustedArea, edgeGeometryLengthFeet } = require("./geometry");
const { normalizeSketchDocument } = require("./schema");
const { resolveFacetBoundary, vertexMap, edgeMap } = require("./topology");

function round2(x) { return Math.round(x * 100) / 100; }

function compareProposal(confirmed, proposed) {
  const c = confirmed == null ? null : Number(confirmed);
  const p = proposed == null ? null : Number(proposed);
  return {
    confirmed: c,
    proposed: p,
    difference: c != null && p != null ? round2(p - c) : null,
  };
}

// Returns an ordered array of proposal/discrepancy/notice records.
function deriveProposals(input) {
  const doc = normalizeSketchDocument(input);
  const out = [];
  const scaleResolved = !!doc.scale.resolved && doc.scale.feetPerUnit != null;
  const fpu = scaleResolved ? Number(doc.scale.feetPerUnit) : null;

  if (!scaleResolved) {
    out.push({ code: "scale_unresolved", decision: "notice", metric: null, target_type: "sketch", target_id: null,
      message: "Scale is not calibrated; dimensional proposals are suppressed." });
    return out;
  }

  const vmap = vertexMap(doc);
  const emap = edgeMap(doc);

  // Facet areas (pitch-adjusted, converted to real sq ft). Uses the SAME authoritative boundary as
  // validation: connected_graph derives from the ordered edge loop, manual_polygon from vertexIds.
  // A facet whose boundary is structurally broken (e.g. contradictory vertexIds, missing edges) is
  // skipped — the proposal engine never quietly falls back to a contradictory vertex boundary.
  (doc.facets || []).forEach((f) => {
    const res = resolveFacetBoundary(doc, f, vmap, emap);
    if (res.error || res.points.length < 3) return;
    const pts = res.points;
    const planUnits = polygonArea(pts);
    const planSqft = planUnits * fpu * fpu;
    const proposed = round2(pitchAdjustedArea(planSqft, f.pitch_rise || 0));
    const confirmed = f.confirmed_area_sqft != null ? Number(f.confirmed_area_sqft) : null;
    out.push({
      code: "facet_area", decision: "proposal", metric: "area_sqft", target_type: "facet", target_id: f.id,
      label: f.label || f.id, confirmed, proposed, difference: confirmed != null ? round2(proposed - confirmed) : null,
    });
  });

  // Edge lengths. Locked edges never receive an overwrite proposal — only a discrepancy notice.
  // Real-world LF comes from the SINGLE shared source (edgeGeometryLengthFeet) so the proposal value
  // and the on-canvas dimension label can never disagree.
  (doc.edges || []).forEach((e) => {
    const a = vmap[e.v1], b = vmap[e.v2];
    if (!a || !b) return;
    const lf = edgeGeometryLengthFeet(doc, e);
    if (lf == null) return;
    const proposed = round2(lf);
    if (e.locked) {
      const confirmed = e.confirmed_length_ft != null ? Number(e.confirmed_length_ft) : null;
      if (confirmed != null && Math.abs(confirmed - proposed) > 0.01) {
        out.push({
          code: "locked_edge_discrepancy", decision: "discrepancy", metric: "length_ft", target_type: "edge",
          target_id: e.id, confirmed, proposed, difference: round2(proposed - confirmed),
          message: "Locked measured length differs from drawn geometry; confirmed value kept.",
        });
      }
      return; // never propose an overwrite for a locked edge
    }
    const confirmed = e.confirmed_length_ft != null ? Number(e.confirmed_length_ft) : null;
    out.push({
      code: "edge_length", decision: "proposal", metric: "length_ft", target_type: "edge", target_id: e.id,
      confirmed, proposed, difference: confirmed != null ? round2(proposed - confirmed) : null,
    });
  });

  return out;
}

module.exports = { deriveProposals, compareProposal, round2 };
