// Structure-safe measurement scoping (pure, Node-testable). The Roof Sketch Editor must only ever
// receive the relational records that belong to the Structure being edited — never facets/edges/
// penetrations from other structures. Identity is by relational ownership only, NEVER by type/length.

const sameId = (a, b) => a != null && b != null && String(a) === String(b);

export function scopeFacetsForStructure(facets, structureId) {
  return (facets || []).filter((f) => sameId(f.structure_id, structureId));
}

export function facetIdSet(scopedFacets) {
  return new Set((scopedFacets || []).map((f) => String(f.id)));
}

// An edge belongs to the structure if EITHER of its facets (shared edges have two) is in-structure.
export function scopeEdgesForStructure(edges, scopedFacets) {
  const ids = facetIdSet(scopedFacets);
  return (edges || []).filter(
    (e) => (e.facet_id != null && ids.has(String(e.facet_id))) ||
           (e.facet_id_secondary != null && ids.has(String(e.facet_id_secondary))),
  );
}

export function scopePenetrationsForStructure(penetrations, scopedFacets) {
  const ids = facetIdSet(scopedFacets);
  return (penetrations || []).filter((p) => p.facet_id != null && ids.has(String(p.facet_id)));
}

// Convenience: everything the editor needs for one structure, derived deterministically.
export function scopeForStructure({ structure, facets, edges, penetrations }) {
  const sid = structure?.id;
  const scopedFacets = scopeFacetsForStructure(facets, sid);
  return {
    facets: scopedFacets,
    edges: scopeEdgesForStructure(edges, scopedFacets),
    penetrations: scopePenetrationsForStructure(penetrations, scopedFacets),
  };
}

// Read-only summary of already-scoped measurements for the Roof Sketch reference panel. Types are raw;
// the UI formats labels/pitch. Pure + Node-testable.
const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
export function summarizeScoped({ facets = [], edges = [], penetrations = [] } = {}) {
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
  return { planes, lines, pens, totals: { area: Math.round(area * 10) / 10, squares: Math.round(area) / 100, planeCount: planes.length } };
}
