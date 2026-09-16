"use strict";
const RS = require('@roofspan/roof-sketch-core');
const numOr = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

// A serializable snapshot of the drawing displayed on one measurement card. The full-size viewer
// consumes this same document; it must not replace it with a separately persisted sketch.
function buildMeasurementRoofPreview({ revisionId, revisionNumber, updatedAt, structure, facets = [], edges = [], penetrations = [], stale = false }) {
  const s = structure || {};
  const key = s.id || s.ref;
  const scoped = facets.filter(f => (s.ref != null && f.structure_ref === s.ref) || (s.id != null && f.structure_id === s.id));
  const nf = scoped.map(f => ({
    id: String(f.id || f.ref), structure_id: key, label: f.facet_label, facet_label: f.facet_label,
    pitch_rise: numOr(f.pitch_rise), width_ft: numOr(f.width_ft), length_ft: numOr(f.length_ft), area_sqft: numOr(f.area_sqft),
  }));
  const ids = new Set(nf.map(f => f.id));
  const fkey = (id, ref) => String(id != null ? id : (ref != null ? ref : ''));
  const ne = edges.map(e => ({
    id: String(e.id || e.ref), edge_type: e.edge_type, length_ft: numOr(e.length_ft),
    facet_id: fkey(e.facet_id, e.facet_ref),
    facet_id_secondary: e.facet_id_secondary != null || e.facet_ref_secondary != null ? fkey(e.facet_id_secondary, e.facet_ref_secondary) : null,
  })).filter(e => ids.has(e.facet_id) || (e.facet_id_secondary && ids.has(e.facet_id_secondary)));
  const np = penetrations.map(p => ({
    id: String(p.id || p.ref), facet_id: fkey(p.facet_id, p.facet_ref), pen_type: p.pen_type, quantity: p.quantity,
  })).filter(p => ids.has(p.facet_id));
  const snapshot = {
    revision_id: revisionId, revision_number: revisionNumber, structure_id: key,
    structure_name: s.name || 'Roof', updated_at: updatedAt || null, stale: !!stale,
    measurement_detail: { id: revisionId, structures: [{ id: key }], facets: nf, edges: ne, penetrations: np },
    document: null, status: scoped.length ? 'unavailable' : 'empty',
  };
  if (!scoped.length) return snapshot;
  try {
    const result = RS.generateSketchGeometry({ structure: { id: key }, facets: nf, edges: ne, penetrations: [] });
    if (result.document?.vertices?.length && result.document?.facets?.length) {
      snapshot.document = result.document;
      snapshot.status = 'ok';
    }
  } catch (_) { /* The card and viewer share the same unavailable state. */ }
  return snapshot;
}

function matchesPreviewRoute(preview, revisionId, structureId) {
  return !!preview && preview.revision_id === revisionId && preview.structure_id === structureId;
}
module.exports = { buildMeasurementRoofPreview, matchesPreviewRoute };
