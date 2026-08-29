"use strict";
// Pure Field wiring adapters (Node-testable; NO React/RN). These are the SAME helpers the RoofSketch
// screen + canvas call in production, so contracts exercise real integration paths (not idealized
// inputs). All topology/geometry stays in @roofspan/roof-sketch-core.
const RS = require("@roofspan/roof-sketch-core");
const VIEW = require("./roofSketchView");
const { resolveInitialSketch } = require("./roofSketchFieldController");

const DRAG_THRESHOLD_PX = 8;

// Resolve the read-through cache envelope { data, stale, cachedAt, error } into the pure resolver's
// `server` shape, keeping the local draft authoritative. Returns { initial, statusMeta }.
function resolveFieldSketchLoad({ draft, sketchResult, structureId } = {}) {
  const server = sketchResult && sketchResult.data ? sketchResult.data : null;
  const initial = resolveInitialSketch({ draft, server, structureId });
  const statusMeta = {
    stale: !!(sketchResult && sketchResult.stale),
    cachedAt: (sketchResult && sketchResult.cachedAt) || null,
    error: (sketchResult && sketchResult.error) || null,
  };
  return { initial, statusMeta };
}

// Map the screen's snake_case route ids onto the controller's camelCase argument names (the controller
// naming is already contract-tested and must NOT change).
function makeFieldEditorArgs({ revision_id, structure_id, initial, persist } = {}) {
  return { revisionId: revision_id, structureId: structure_id, initial, persist };
}

function movedBeyondThreshold(aScreen, bScreen, thresholdPx = DRAG_THRESHOLD_PX) {
  return Math.hypot(bScreen[0] - aScreen[0], bScreen[1] - aScreen[1]) > thresholdPx;
}

// The authoritative pointer-up candidate is the last SYNCHRONOUSLY stored snap candidate on the gesture
// ref — never React render state (which may not have flushed).
function pickReleaseCandidate(gesture, fallback) {
  return gesture && gesture.snapCandidate ? gesture.snapCandidate : fallback;
}

// Two-finger transform with focal continuity: the model point under the ORIGINAL midpoint stays under
// the NEW midpoint at the new scale (constant separation => pure pan; changing separation => pan+zoom).
function applyTwoTouchView(view, prev, now, opts = {}) {
  const ratio = prev.dist > 0 ? now.dist / prev.dist : 1;
  const ns = VIEW.clampScale(view.scale * ratio, opts.min, opts.max);
  const mx = (prev.mid[0] - view.tx) / view.scale;
  const my = (prev.mid[1] - view.ty) / view.scale;
  return { scale: ns, tx: now.mid[0] - mx * ns, ty: now.mid[1] - my * ns };
}

// Join two edges; report when the caller must supply an explicit result type. Returns
// { ok, doc?, edgeId?, reason?, needsType }.
function attemptJoin(doc, aId, bId, resultType) {
  const r = RS.joinEdges(doc, aId, bId, resultType ? { resultType } : undefined);
  if (r.ok) return { ok: true, doc: r.doc, edgeId: r.edgeId, needsType: false };
  return { ok: false, reason: r.reason, needsType: r.reason === "type_conflict" };
}

// Build a connected facet from selected edges, but only commit if the operation itself introduces no
// NEW hard structural error. Returns { ok, doc?, facetId?, reason? } (original doc preserved on reject).
function commitFacetCreate(doc, edgeIds) {
  if (!edgeIds || edgeIds.length < 3) return { ok: false, reason: "facet_needs_three_edges", doc };
  const r = RS.createFacet(doc, edgeIds);
  if (!RS.validateMutation(doc, r.doc).ok) return { ok: false, reason: "facet_would_be_invalid", doc };
  return { ok: true, doc: r.doc, facetId: r.facetId };
}

function commitManualCreate(doc, vertexIds) {
  if (!vertexIds || vertexIds.length < 3) return { ok: false, reason: "polygon_needs_three_points", doc };
  const r = RS.createManualFacet(doc, vertexIds);
  if (!RS.validateMutation(doc, r.doc).ok) return { ok: false, reason: "facet_would_be_invalid", doc };
  return { ok: true, doc: r.doc, facetId: r.facetId };
}

module.exports = {
  DRAG_THRESHOLD_PX,
  resolveFieldSketchLoad,
  makeFieldEditorArgs,
  movedBeyondThreshold,
  pickReleaseCandidate,
  applyTwoTouchView,
  attemptJoin,
  commitFacetCreate,
  commitManualCreate,
};
