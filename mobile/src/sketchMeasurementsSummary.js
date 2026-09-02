"use strict";
// Pure, Node-testable summary of the measurements the user entered, scoped to ONE structure, for the
// read-only reference panel inside the Roof Sketch. Ownership is relational only (structure_id / facet_id),
// never by type/length. Types are returned raw; the UI formats labels/pitch.

const sameId = (a, b) => a != null && b != null && String(a) === String(b);
const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };

function summarizeScoped({ facets = [], edges = [], penetrations = [] } = {}) {
  const planes = facets.map((f, i) => ({
    id: f.id != null ? f.id : (f.ref || i),
    label: f.facet_label || `F${i + 1}`,
    pitch_rise: (f.pitch_rise === "" || f.pitch_rise == null) ? null : f.pitch_rise,
    area: num(f.area_sqft),
    width: (f.width_ft == null || f.width_ft === "") ? null : num(f.width_ft),
    length: (f.length_ft == null || f.length_ft === "") ? null : num(f.length_ft),
  }));
  const lineMap = {};
  edges.forEach((e) => { const t = e.edge_type || "other"; lineMap[t] = (lineMap[t] || 0) + num(e.length_ft); });
  const lines = Object.keys(lineMap).map((type) => ({ type, lf: Math.round(lineMap[type] * 10) / 10 }));
  const penMap = {};
  penetrations.forEach((p) => { const t = p.pen_type || "other"; const q = parseInt(p.quantity, 10); penMap[t] = (penMap[t] || 0) + (Number.isFinite(q) ? q : 1); });
  const pens = Object.keys(penMap).filter((t) => penMap[t] > 0).map((type) => ({ type, qty: penMap[type] }));
  const area = planes.reduce((s, p) => s + p.area, 0);
  return {
    planes, lines, pens,
    totals: { area: Math.round(area * 10) / 10, squares: Math.round(area) / 100, planeCount: planes.length },
  };
}

// Scope a full Measurement Revision detail to a structure, then summarize.
function summarizeStructureMeasurements(detail, structureId) {
  const facetsAll = (detail && detail.facets) || [];
  const edgesAll = (detail && detail.edges) || [];
  const pensAll = (detail && detail.penetrations) || [];
  const facets = facetsAll.filter((f) => sameId(f.structure_id, structureId));
  const idset = new Set(facets.map((f) => String(f.id)));
  const edges = edgesAll.filter((e) =>
    (e.facet_id != null && idset.has(String(e.facet_id))) ||
    (e.facet_id_secondary != null && idset.has(String(e.facet_id_secondary))));
  const penetrations = pensAll.filter((p) => p.facet_id != null && idset.has(String(p.facet_id)));
  return summarizeScoped({ facets, edges, penetrations });
}

module.exports = { summarizeScoped, summarizeStructureMeasurements };
