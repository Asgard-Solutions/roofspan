"use strict";
// Canonical roof sketch document: creation, normalization, versioning rules.

const SCHEMA_VERSION = 1;
const EDIT_MODES = ["connected_graph", "manual_polygon"];
const EDGE_TYPES = ["eave", "rake", "ridge", "hip", "valley", "dead_valley", "sidewall", "headwall", "transition", "unclassified"];

function createSketchDocument({ structureId = null, editMode = "connected_graph" } = {}) {
  return {
    schema_version: SCHEMA_VERSION,
    edit_mode: EDIT_MODES.includes(editMode) ? editMode : "connected_graph",
    structure_id: structureId,
    vertices: [],
    edges: [],
    facets: [],
    penetrations: [],
    scale: { resolved: false, feetPerUnit: null, feet_per_unit: null, method: null },
    proposal_decisions: [],
    placement_resolutions: [],
    validation: { valid: true, errors: [], warnings: [] },
  };
}

// Fill defaults for any partial/legacy document so callers can trust the shape.
function normalizeSketchDocument(doc) {
  const d = doc && typeof doc === "object" ? doc : {};
  const base = createSketchDocument({
    structureId: d.structure_id != null ? d.structure_id : null,
    editMode: d.edit_mode,
  });
  const scale = d.scale && typeof d.scale === "object" ? d.scale : base.scale;
  const feetPerUnit = scale.feetPerUnit != null ? scale.feetPerUnit : (scale.feet_per_unit != null ? scale.feet_per_unit : null);
  return {
    schema_version: SCHEMA_VERSION,
    edit_mode: EDIT_MODES.includes(d.edit_mode) ? d.edit_mode : "connected_graph",
    structure_id: d.structure_id != null ? d.structure_id : null,
    vertices: Array.isArray(d.vertices) ? d.vertices : [],
    edges: Array.isArray(d.edges) ? d.edges : [],
    facets: Array.isArray(d.facets) ? d.facets : [],
    penetrations: Array.isArray(d.penetrations) ? d.penetrations : [],
    scale: {
      resolved: !!scale.resolved && feetPerUnit != null,
      feetPerUnit,
      feet_per_unit: feetPerUnit,
      method: scale.method || null,
    },
    proposal_decisions: Array.isArray(d.proposal_decisions) ? d.proposal_decisions : [],
    placement_resolutions: Array.isArray(d.placement_resolutions) ? d.placement_resolutions : [],
    validation: d.validation && typeof d.validation === "object" ? d.validation : { valid: true, errors: [], warnings: [] },
  };
}

module.exports = { SCHEMA_VERSION, EDIT_MODES, EDGE_TYPES, createSketchDocument, normalizeSketchDocument };
