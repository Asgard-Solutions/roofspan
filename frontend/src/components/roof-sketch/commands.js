// Pure editor commands. Each returns the NEXT canonical sketch document (never mutates the input).
// The shared @roofspan/roof-sketch-core remains the single source of geometry/validation/proposal math.
import { normalizeSketchDocument, calibrateScale, distance, projectPointToSegment } from "@roofspan/roof-sketch-core";

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

// ---- Phase 3: topology-safe geometry operations (all pure; return {ok, doc, reason?}) ----

// An edge carries authoritative relational/measurement semantics and must never be silently
// split/joined (that would make the one-to-one MeasurementEdge identity ambiguous).
export function edgeIsProtected(e) {
  return !!e && (e.measurement_edge_id != null || e.relational_edge_id != null || e.locked === true || e.confirmed_length_ft != null);
}

const pairKey = (a, b) => [a, b].sort().join("::");
// harmless presentation metadata the children may inherit on a split (never relational/confirmed/lock)
const safeEdgeMeta = (e) => ({ type: e.type });

function dropEdgeDecisions(list, edgeId) {
  return (list || []).filter((x) => !(x.target_type === "edge" && String(x.target_id) === String(edgeId)));
}

// Split an edge at the point projected onto its own segment. Rejects protected edges and near-endpoint
// clicks (reuse the endpoint instead of making a zero-length child). Updates EVERY facet loop that used
// the edge, preserving each loop's direction. endpointTol is in model units.
export function splitEdgeSafe(doc, edgeId, x, y, { endpointTol = 1e-6 } = {}) {
  const e = eById(doc, edgeId);
  if (!e) return { ok: false, reason: "edge_not_found", doc };
  if (edgeIsProtected(e)) return { ok: false, reason: "edge_protected", doc };
  const a = vById(doc, e.v1), b = vById(doc, e.v2);
  if (!a || !b) return { ok: false, reason: "broken_edge_reference", doc };
  const proj = projectPointToSegment([Number(x), Number(y)], [a.x, a.y], [b.x, b.y]);
  const dA = distance(proj.point, [a.x, a.y]);
  const dB = distance(proj.point, [b.x, b.y]);
  if (dA <= endpointTol) return { ok: false, reason: "endpoint_reuse", vertexId: e.v1, doc };
  if (dB <= endpointTol) return { ok: false, reason: "endpoint_reuse", vertexId: e.v2, doc };
  const d = clone(doc);
  const nv = { id: nid("v"), x: proj.point[0], y: proj.point[1] };
  d.vertices = [...d.vertices, nv];
  const ea = { id: nid("e"), v1: e.v1, v2: nv.id, ...safeEdgeMeta(e) };
  const eb = { id: nid("e"), v1: nv.id, v2: e.v2, ...safeEdgeMeta(e) };
  d.edges = d.edges.filter((x2) => x2.id !== edgeId).concat([ea, eb]);
  d.facets = d.facets.map((f) => {
    const ids = f.edgeIds || [];
    const i = ids.indexOf(edgeId);
    if (i < 0) return f;
    const prev = eById(doc, ids[(i - 1 + ids.length) % ids.length]);
    const prevTouchesV1 = prev && (prev.v1 === e.v1 || prev.v2 === e.v1);
    const inserted = prevTouchesV1 ? [ea.id, eb.id] : [eb.id, ea.id];
    return { ...f, edgeIds: ids.slice(0, i).concat(inserted).concat(ids.slice(i + 1)), vertexIds: [] };
  });
  d.proposal_decisions = dropEdgeDecisions(d.proposal_decisions, edgeId);
  return { ok: true, doc: d, vertexId: nv.id, edgeIds: [ea.id, eb.id] };
}

// Merge movingVertexId onto targetVertexId: rewire incident edges, drop self-loops, collapse duplicate
// edges only when semantically compatible, keep facet loops valid. Rejects incompatible collapses.
export function mergeVertices(doc, movingVertexId, targetVertexId) {
  if (movingVertexId === targetVertexId) return { ok: false, reason: "same_vertex", doc };
  if (!vById(doc, movingVertexId) || !vById(doc, targetVertexId)) return { ok: false, reason: "vertex_not_found", doc };
  const d = clone(doc);
  const rewire = (id) => (id === movingVertexId ? targetVertexId : id);
  let edges = d.edges.map((e) => ({ ...e, v1: rewire(e.v1), v2: rewire(e.v2) }));
  const removed = [];
  edges = edges.filter((e) => { if (e.v1 === e.v2) { removed.push(e.id); return false; } return true; });
  // collapse duplicates (same unordered endpoint pair)
  const byPair = {}; const keptFor = {};
  for (const e of edges) {
    const k = pairKey(e.v1, e.v2);
    if (!byPair[k]) { byPair[k] = e; keptFor[k] = e.id; continue; }
    const a = byPair[k];
    const typeCompat = a.type === e.type || a.type === "unclassified" || e.type === "unclassified";
    const relConflict = (a.measurement_edge_id != null && e.measurement_edge_id != null && a.measurement_edge_id !== e.measurement_edge_id) ||
      (a.confirmed_length_ft != null && e.confirmed_length_ft != null && a.confirmed_length_ft !== e.confirmed_length_ft) ||
      (!!a.locked !== !!e.locked) || (a.relational_edge_id != null && e.relational_edge_id != null && a.relational_edge_id !== e.relational_edge_id);
    if (!typeCompat || relConflict) return { ok: false, reason: "incompatible_duplicate_edges", doc };
    removed.push(e.id); // drop the duplicate; keep byPair[k]
  }
  edges = edges.filter((e) => !removed.includes(e.id));
  const remap = (id) => { const e0 = d.edges.find((x) => x.id === id); if (!e0) return id; return keptFor[pairKey(rewire(e0.v1), rewire(e0.v2))] || id; };
  d.edges = edges;
  d.vertices = d.vertices.filter((v) => v.id !== movingVertexId);
  d.facets = d.facets.map((f) => {
    if (!f.edgeIds || !f.edgeIds.length) return f;
    const mapped = f.edgeIds.map(remap).filter((id, i, arr) => id !== arr[i - 1]); // drop consecutive dupes
    return { ...f, edgeIds: mapped };
  });
  return { ok: true, doc: d };
}

// Join two edges that share exactly one middle vertex into a single edge A--C.
export function joinEdges(doc, aId, bId, { resultType } = {}) {
  const ea = eById(doc, aId), eb = eById(doc, bId);
  if (!ea || !eb) return { ok: false, reason: "edge_not_found", doc };
  if (aId === bId) return { ok: false, reason: "same_edge", doc };
  if (edgeIsProtected(ea) || edgeIsProtected(eb)) return { ok: false, reason: "edge_protected", doc };
  const aSet = [ea.v1, ea.v2], bSet = [eb.v1, eb.v2];
  const shared = aSet.filter((v) => bSet.includes(v));
  if (shared.length !== 1) return { ok: false, reason: "no_single_shared_vertex", doc };
  const mid = shared[0];
  const A = ea.v1 === mid ? ea.v2 : ea.v1;
  const C = eb.v1 === mid ? eb.v2 : eb.v1;
  if (A === C) return { ok: false, reason: "degenerate_join", doc };
  const midIncident = doc.edges.filter((e) => e.v1 === mid || e.v2 === mid);
  if (midIncident.length !== 2) return { ok: false, reason: "middle_vertex_has_additional_connections", doc };
  if (doc.edges.some((e) => pairKey(e.v1, e.v2) === pairKey(A, C))) return { ok: false, reason: "duplicate_outer_edge", doc };
  let type;
  if (ea.type === eb.type) type = ea.type;
  else if (ea.type === "unclassified") type = eb.type;
  else if (eb.type === "unclassified") type = ea.type;
  else { if (!resultType) return { ok: false, reason: "type_conflict", doc }; type = resultType; }
  // every facet touching one source edge must contain the two as a consecutive pair
  for (const f of doc.facets || []) {
    const ids = f.edgeIds || [];
    const hasA = ids.includes(aId), hasB = ids.includes(bId);
    if (hasA !== hasB) return { ok: false, reason: "facet_boundary_mismatch", doc };
    if (hasA && hasB) {
      const adjacent = ids.some((id, i) => { const nx = ids[(i + 1) % ids.length]; return (id === aId && nx === bId) || (id === bId && nx === aId); });
      if (!adjacent) return { ok: false, reason: "facet_boundary_mismatch", doc };
    }
  }
  const d = clone(doc);
  const joined = { id: ea.id, v1: A, v2: C, type };
  d.edges = d.edges.filter((e) => e.id !== aId && e.id !== bId).concat([joined]);
  d.vertices = d.vertices.filter((v) => v.id !== mid);
  d.facets = d.facets.map((f) => {
    const ids = f.edgeIds || [];
    if (!ids.includes(aId) && !ids.includes(bId)) return f;
    const out = [];
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i], nx = ids[(i + 1) % ids.length];
      if ((id === aId && nx === bId) || (id === bId && nx === aId)) { out.push(joined.id); i++; }
      else if (id === aId || id === bId) out.push(joined.id);
      else out.push(id);
    }
    return { ...f, edgeIds: out.filter((id, i, arr) => id !== arr[i - 1]), vertexIds: [] };
  });
  d.proposal_decisions = dropEdgeDecisions(d.proposal_decisions, bId);
  return { ok: true, doc: d, edgeId: joined.id };
}
