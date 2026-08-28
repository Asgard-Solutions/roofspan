// Pure editor commands. Each returns the NEXT canonical sketch document (never mutates the input).
// The shared @roofspan/roof-sketch-core remains the single source of geometry/validation/proposal math.
import { normalizeSketchDocument, calibrateScale, distance } from "@roofspan/roof-sketch-core";

let _seq = 0;
export const nid = (p) => `${p}_${Date.now().toString(36)}${(_seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

const clone = (doc) => ({
  ...doc,
  vertices: [...(doc.vertices || [])],
  edges: [...(doc.edges || [])],
  facets: [...(doc.facets || [])],
  penetrations: [...(doc.penetrations || [])],
  proposal_decisions: [...(doc.proposal_decisions || [])],
  scale: { ...(doc.scale || {}) },
});

export const vById = (doc, id) => (doc.vertices || []).find((v) => v.id === id) || null;
export const eById = (doc, id) => (doc.edges || []).find((e) => e.id === id) || null;
export const fById = (doc, id) => (doc.facets || []).find((f) => f.id === id) || null;

export function addVertex(doc, x, y) {
  const d = clone(doc);
  const v = { id: nid("v"), x: Number(x), y: Number(y) };
  d.vertices = [...d.vertices, v];
  return { doc: d, vertexId: v.id };
}

export function moveVertex(doc, vertexId, x, y) {
  const d = clone(doc);
  d.vertices = d.vertices.map((v) => (v.id === vertexId ? { ...v, x: Number(x), y: Number(y) } : v));
  return d;
}

export function deleteVertex(doc, vertexId) {
  let d = clone(doc);
  const usingEdges = d.edges.filter((e) => e.v1 === vertexId || e.v2 === vertexId).map((e) => e.id);
  d.vertices = d.vertices.filter((v) => v.id !== vertexId);
  usingEdges.forEach((eid) => { d = deleteEdge(d, eid); });
  return d;
}

export function addEdge(doc, v1, v2, type = "unclassified") {
  if (v1 === v2) return doc;
  const exists = (doc.edges || []).some((e) => (e.v1 === v1 && e.v2 === v2) || (e.v1 === v2 && e.v2 === v1));
  if (exists) return doc;
  const d = clone(doc);
  const e = { id: nid("e"), v1, v2, type };
  d.edges = [...d.edges, e];
  return { doc: d, edgeId: e.id };
}

export function setEdgeType(doc, edgeId, type) {
  const d = clone(doc);
  d.edges = d.edges.map((e) => (e.id === edgeId ? { ...e, type } : e));
  return d;
}

export function deleteEdge(doc, edgeId) {
  const d = clone(doc);
  d.edges = d.edges.filter((e) => e.id !== edgeId);
  // any facet that used this edge is no longer a valid loop -> drop the facet's boundary reference
  d.facets = d.facets.filter((f) => !(f.edgeIds || []).includes(edgeId));
  return d;
}

// Split an edge at (x,y): insert a vertex and two edges, preserving facet loop order.
export function splitEdge(doc, edgeId, x, y) {
  const e = eById(doc, edgeId);
  if (!e) return doc;
  let d = clone(doc);
  const nv = { id: nid("v"), x: Number(x), y: Number(y) };
  d.vertices = [...d.vertices, nv];
  const ea = { id: nid("e"), v1: e.v1, v2: nv.id, type: e.type };
  const eb = { id: nid("e"), v1: nv.id, v2: e.v2, type: e.type };
  d.edges = d.edges.filter((x2) => x2.id !== edgeId).concat([ea, eb]);
  d.facets = d.facets.map((f) => {
    const ids = f.edgeIds || [];
    const i = ids.indexOf(edgeId);
    if (i < 0) return f;
    const prev = eById(doc, ids[(i - 1 + ids.length) % ids.length]);
    const prevTouchesV1 = prev && (prev.v1 === e.v1 || prev.v2 === e.v1);
    const inserted = prevTouchesV1 ? [ea.id, eb.id] : [eb.id, ea.id];
    const next = ids.slice(0, i).concat(inserted).concat(ids.slice(i + 1));
    return { ...f, edgeIds: next, vertexIds: [] }; // let the edge loop stay authoritative
  });
  return d;
}

export function createFacet(doc, edgeIds, extra = {}) {
  const d = clone(doc);
  const f = { id: nid("f"), edgeIds: [...edgeIds], vertexIds: [], pitch_rise: 0, orientation: null, label: `F${d.facets.length + 1}`, ...extra };
  d.facets = [...d.facets, f];
  return { doc: d, facetId: f.id };
}

export function createManualFacet(doc, vertexIds, extra = {}) {
  const d = clone(doc);
  const f = { id: nid("f"), vertexIds: [...vertexIds], edgeIds: [], pitch_rise: 0, orientation: null, label: `F${d.facets.length + 1}`, ...extra };
  d.facets = [...d.facets, f];
  return { doc: d, facetId: f.id };
}

export function deleteFacet(doc, facetId) {
  const d = clone(doc);
  d.facets = d.facets.filter((f) => f.id !== facetId);
  return d;
}

export function setFacetPitch(doc, facetId, pitchRise) {
  const d = clone(doc);
  d.facets = d.facets.map((f) => (f.id === facetId ? { ...f, pitch_rise: Number(pitchRise) || 0 } : f));
  return d;
}

export function setFacetOrientation(doc, facetId, orientation) {
  const d = clone(doc);
  d.facets = d.facets.map((f) => (f.id === facetId ? { ...f, orientation: orientation || null } : f));
  return d;
}

export function setFacetLabel(doc, facetId, label) {
  const d = clone(doc);
  d.facets = d.facets.map((f) => (f.id === facetId ? { ...f, label } : f));
  return d;
}

// scale from a known real length on a specific edge (or an explicit canvas distance)
export function setScale(doc, { edgeId, realFeet, canvasDistance, method } = {}) {
  let cd = canvasDistance;
  if (cd == null && edgeId) {
    const e = eById(doc, edgeId);
    const a = e && vById(doc, e.v1);
    const b = e && vById(doc, e.v2);
    if (a && b) cd = distance([a.x, a.y], [b.x, b.y]);
  }
  const d = clone(doc);
  d.scale = calibrateScale({ canvasDistance: cd, realFeet, method: method || "structure_calibration" });
  return d;
}

export function setConfirmedEdgeLength(doc, edgeId, feet) {
  const d = clone(doc);
  d.edges = d.edges.map((e) => (e.id === edgeId ? { ...e, confirmed_length_ft: feet == null || feet === "" ? null : Number(feet) } : e));
  return d;
}

export function lockEdge(doc, edgeId) {
  const d = clone(doc);
  d.edges = d.edges.map((e) => (e.id === edgeId ? { ...e, locked: true } : e));
  return d;
}

export function unlockEdge(doc, edgeId) {
  const d = clone(doc);
  d.edges = d.edges.map((e) => (e.id === edgeId ? { ...e, locked: false } : e));
  return d;
}

export function placePenetration(doc, x, y, extra = {}) {
  const d = clone(doc);
  const p = { id: nid("pen"), x: Number(x), y: Number(y), pen_type: "pipe_boot", ...extra };
  d.penetrations = [...d.penetrations, p];
  return { doc: d, penetrationId: p.id };
}

export function movePenetration(doc, penId, x, y) {
  const d = clone(doc);
  d.penetrations = d.penetrations.map((p) => (p.id === penId ? { ...p, x: Number(x), y: Number(y) } : p));
  return d;
}

export function setPenetrationType(doc, penId, penType) {
  const d = clone(doc);
  d.penetrations = d.penetrations.map((p) => (p.id === penId ? { ...p, pen_type: penType } : p));
  return d;
}

export function deletePenetration(doc, penId) {
  const d = clone(doc);
  d.penetrations = d.penetrations.filter((p) => p.id !== penId);
  return d;
}

// Explicit proposal decision. decision: "pending_accept" | "accepted" | "keep_current".
export function setProposalDecision(doc, { targetType, targetId, metric, decision, value } = {}) {
  const d = clone(doc);
  const others = d.proposal_decisions.filter((x) => !(x.target_type === targetType && x.target_id === targetId && x.metric === metric));
  d.proposal_decisions = [...others, { target_type: targetType, target_id: targetId, metric, decision, value: value ?? null, proposed_value: value ?? null, at: new Date().toISOString() }];
  return d;
}

// Replace the whole decisions array (used when the proposal lifecycle computes the next set).
export function setDecisions(doc, decisions) {
  const d = clone(doc);
  d.proposal_decisions = [...(decisions || [])];
  return d;
}

export function decisionFor(doc, targetType, targetId, metric) {
  return (doc.proposal_decisions || []).find((x) => x.target_type === targetType && x.target_id === targetId && x.metric === metric) || null;
}

// ---- explicit relational mapping (one-to-one within the sketch) ----
// A sketch facet is linked to at most one MeasurementFacet and vice-versa. Mapping is ALWAYS explicit;
// identity is NEVER inferred from length/type/position. We never silently steal an existing mapping.
export function isMeasurementFacetTaken(doc, measurementFacetId, exceptFacetId) {
  return (doc.facets || []).some((f) => f.id !== exceptFacetId && f.measurement_facet_id != null && String(f.measurement_facet_id) === String(measurementFacetId));
}

export function setFacetMeasurementLink(doc, facetId, measurementFacetId) {
  // Unlinking (null) is always allowed. Linking to an already-used MeasurementFacet is refused (no-op).
  if (measurementFacetId != null && isMeasurementFacetTaken(doc, measurementFacetId, facetId)) return doc;
  const d = clone(doc);
  d.facets = d.facets.map((f) => (f.id === facetId ? { ...f, measurement_facet_id: measurementFacetId ?? null } : f));
  return d;
}

export function isMeasurementEdgeTaken(doc, measurementEdgeId, exceptEdgeId) {
  return (doc.edges || []).some((e) => e.id !== exceptEdgeId && e.measurement_edge_id != null && String(e.measurement_edge_id) === String(measurementEdgeId));
}

export function setEdgeMeasurementLink(doc, edgeId, measurementEdgeId) {
  if (measurementEdgeId != null && isMeasurementEdgeTaken(doc, measurementEdgeId, edgeId)) return doc;
  const d = clone(doc);
  const v = measurementEdgeId ?? null;
  // keep both canonical aliases coherent (clone-remap handles measurement_edge_id + relational_edge_id)
  d.edges = d.edges.map((e) => (e.id === edgeId ? { ...e, measurement_edge_id: v, relational_edge_id: v } : e));
  return d;
}

export function setEditMode(doc, mode) {
  return normalizeSketchDocument({ ...clone(doc), edit_mode: mode });
}
