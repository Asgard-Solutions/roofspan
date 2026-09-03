"use strict";
// Measurements -> Proposed Roof Sketch: shared deterministic FOUNDATION (Phase 1).
//
// This module turns ONE structure's already structure-scoped relational measurement records
// (Roof Planes / Roof Lines / Penetrations) into a PROPOSAL result: a partial canonical sketch
// candidate whose facets/edges/penetrations retain their exact relational Measurement identity,
// plus a measurement constraint/topology representation and human-readable diagnostics.
//
// HARD CONTRACT (see business rules):
//   - Pure & deterministic. Identical input -> identical logical proposal. No Date/Math.random.
//   - Identity is RELATIONAL ONLY. Sketch element ids are derived from the measurement record ids;
//     mappings are never inferred from label/type/length/order (no fuzzy matching).
//   - Carries known labels, pitch, confirmed area, confirmed edge length, edge classification,
//     and Primary/Secondary Roof Plane relationships.
//   - NEVER invents XY positions to look valid. Vertices are never fabricated; the scale stays
//     unresolved. A penetration with a plane but no known XY keeps position === null (never faked).
//   - When information is insufficient, it returns diagnostics instead of guessing.
//   - Never saves, queues, mutates measurements, replaces a sketch, or calls the network.
const { createSketchDocument } = require("./schema");

const GENERATOR_VERSION = 1;
const AREA_DIM_TOL = 0.5; // sq ft tolerance for area vs (width * length) consistency

const num = (v) => {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const sid = (v) => (v == null ? null : String(v));
// Deterministic, collision-free sketch id bound to the relational record id.
const sfid = (prefix, id) => `${prefix}_${String(id)}`;
// Stable ordering: by numeric sort field then by relational id string (never by label/type/length).
const bySortThenId = (a, b) => {
  const sa = Number(a && a.sort), sb = Number(b && b.sort);
  const na = Number.isFinite(sa) ? sa : 0, nb = Number.isFinite(sb) ? sb : 0;
  if (na !== nb) return na - nb;
  return String((a && a.id) ?? "").localeCompare(String((b && b.id) ?? ""));
};

// Deterministic FNV-1a hash (32-bit hex) — no randomness, so a proposal can later detect whether the
// Measurements it was built from have changed.
function _hash(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return ("00000000" + (h >>> 0).toString(16)).slice(-8);
}
function _fingerprint(inp) {
  const s = (v) => (v == null ? null : String(v));
  const facets = (Array.isArray(inp.facets) ? inp.facets : []).map((f) => [s(f.id), s(f.structure_id), f.pitch_rise, f.area_sqft, f.width_ft, f.length_ft, f.position_offset_ft, f.orientation_azimuth]).sort((a, b) => (String(a[0]) < String(b[0]) ? -1 : 1));
  const edges = (Array.isArray(inp.edges) ? inp.edges : []).map((e) => [s(e.id), e.edge_type, e.length_ft, s(e.facet_id), s(e.facet_id_secondary)]).sort((a, b) => (String(a[0]) < String(b[0]) ? -1 : 1));
  const pens = (Array.isArray(inp.penetrations) ? inp.penetrations : []).map((p) => [s(p.id), p.pen_type, p.quantity, s(p.facet_id)]).sort((a, b) => (String(a[0]) < String(b[0]) ? -1 : 1));
  return _hash(JSON.stringify({ st: inp.structure && inp.structure.id != null ? String(inp.structure.id) : null, facets, edges, pens }));
}

function generateProposedSketch(input) {
  const inp = input || {};
  const source_fingerprint = _fingerprint(inp);
  const structure = inp.structure || null;
  const facetsIn = Array.isArray(inp.facets) ? inp.facets : [];
  const edgesIn = Array.isArray(inp.edges) ? inp.edges : [];
  const pensIn = Array.isArray(inp.penetrations) ? inp.penetrations : [];

  const diagnostics = [];
  const diag = (severity, code, target_type, target_id, message) =>
    diagnostics.push({ severity, code, target_type, target_id: target_id != null ? String(target_id) : null, message });

  const structureId = structure && structure.id != null ? String(structure.id) : null;
  if (structureId == null) {
    diag("error", "missing_structure", "structure", null, "No structure was provided; cannot generate a proposal.");
  }

  // ---- STRUCTURE ISOLATION (defense in depth) ------------------------------------------------
  // Only records that belong to THIS structure are used. A facet with a foreign/absent structure_id
  // is excluded and reported. Edges/penetrations follow their facet ownership — never by type/length.
  const scopedFacets = [];
  for (const f of facetsIn.slice().sort(bySortThenId)) {
    const fSid = sid(f && f.structure_id);
    if (structureId != null && fSid != null && fSid !== structureId) {
      diag("warning", "foreign_facet", "facet", f.id, "Roof plane belongs to a different structure and was excluded.");
      continue;
    }
    if (f == null || f.id == null) {
      diag("warning", "unidentified_facet", "facet", null, "A roof plane without a relational id was skipped.");
      continue;
    }
    scopedFacets.push(f);
  }
  const facetIdSet = new Set(scopedFacets.map((f) => String(f.id)));

  const inScopeFacet = (fid) => fid != null && facetIdSet.has(String(fid));

  const scopedEdges = [];
  for (const e of edgesIn.slice().sort(bySortThenId)) {
    if (e == null || e.id == null) {
      diag("warning", "unidentified_edge", "edge", null, "A roof line without a relational id was skipped.");
      continue;
    }
    const p = sid(e.facet_id);
    const s = sid(e.facet_id_secondary);
    const pIn = inScopeFacet(p);
    const sIn = inScopeFacet(s);
    if (p == null && s == null) {
      diag("warning", "edge_unassigned", "edge", e.id, "Roof line is not linked to any roof plane; excluded from the candidate.");
      continue;
    }
    // Referenced a plane, but none of them are in this structure's scope -> foreign, never re-pointed.
    if (!pIn && !sIn) {
      diag("warning", "foreign_edge", "edge", e.id, "Roof line references roof plane(s) outside this structure; excluded.");
      continue;
    }
    scopedEdges.push(e);
  }

  const scopedPens = [];
  for (const pen of pensIn.slice().sort(bySortThenId)) {
    if (pen == null || pen.id == null) {
      diag("warning", "unidentified_penetration", "penetration", null, "A penetration without a relational id was skipped.");
      continue;
    }
    const f = sid(pen.facet_id);
    if (f == null) {
      diag("warning", "penetration_unassigned", "penetration", pen.id, "Penetration is not linked to a roof plane; excluded from the candidate.");
      continue;
    }
    if (!inScopeFacet(f)) {
      diag("warning", "foreign_penetration", "penetration", pen.id, "Penetration references a roof plane outside this structure; excluded.");
      continue;
    }
    scopedPens.push(pen);
  }

  if (scopedFacets.length === 0) {
    diag("error", "no_roof_planes", "structure", structureId, "This structure has no roof planes to generate a sketch from.");
  }

  // ---- CANDIDATE FACETS (relational identity + carried attributes; NO invented geometry) ------
  const doc = createSketchDocument({ structureId });
  const facetMappings = [];
  const constraintPlanes = [];
  const facetSketchIdByMid = {};

  for (const f of scopedFacets) {
    const mid = String(f.id);
    const skId = sfid("msf", mid);
    facetSketchIdByMid[mid] = skId;
    const pitch = num(f.pitch_rise);
    const area = num(f.area_sqft);
    const width = num(f.width_ft);
    const length = num(f.length_ft);
    const positionOffset = num(f.position_offset_ft);
    const azimuth = num(f.orientation_azimuth);

    if (pitch == null) diag("error", "missing_pitch", "facet", mid, "Roof plane has no pitch; geometry cannot be constrained.");
    if (area == null || !(area > 0)) diag("error", "missing_area", "facet", mid, "Roof plane has no positive area.");
    if (width != null && length != null && area != null && Math.abs(width * length - area) > AREA_DIM_TOL) {
      diag("info", "area_dimension_mismatch", "facet", mid,
        "Roof plane area does not equal Width x Length; the confirmed area is kept as authoritative.");
    }

    doc.facets.push({
      id: skId,
      measurement_facet_id: mid,
      relational_facet_id: mid,
      label: (f.facet_label != null && f.facet_label !== "") ? String(f.facet_label) : `F${constraintPlanes.length + 1}`,
      pitch_rise: pitch,
      confirmed_area_sqft: area,
      width_ft: width,
      length_ft: length,
      position_offset_ft: positionOffset,
      orientation_azimuth: azimuth,
      roof_material: f.roof_material != null ? f.roof_material : null,
      edgeIds: [],   // filled below from relational roof-line links (topology intent, not a drawn loop)
      vertexIds: [], // never fabricated in this phase
    });
    facetMappings.push({ sketch_facet_id: skId, measurement_facet_id: mid });
    constraintPlanes.push({
      measurement_facet_id: mid,
      label: (f.facet_label != null && f.facet_label !== "") ? String(f.facet_label) : `F${constraintPlanes.length + 1}`,
      pitch_rise: pitch, area_sqft: area, width_ft: width, length_ft: length,
      position_offset_ft: positionOffset,
      orientation_azimuth: azimuth, edge_ids: [],
    });
  }
  const planeByMid = {};
  constraintPlanes.forEach((p) => { planeByMid[p.measurement_facet_id] = p; });

  // ---- CANDIDATE EDGES (classification + confirmed length + Primary/Secondary plane links) -----
  const edgeMappings = [];
  const constraintLines = [];
  const adjacency = [];

  for (const e of scopedEdges) {
    const mid = String(e.id);
    const skId = sfid("mse", mid);
    const type = (e.edge_type != null && e.edge_type !== "") ? String(e.edge_type) : "unclassified";
    const length = num(e.length_ft);
    const pMid = inScopeFacet(e.facet_id) ? String(e.facet_id) : null;
    const sMid = inScopeFacet(e.facet_id_secondary) ? String(e.facet_id_secondary) : null;
    const primarySketch = pMid != null ? facetSketchIdByMid[pMid] : null;
    const secondarySketch = sMid != null ? facetSketchIdByMid[sMid] : null;
    const shared = !!(primarySketch && secondarySketch);

    if (length == null || !(length > 0)) diag("warning", "edge_no_length", "edge", mid, "Roof line has no positive confirmed length.");

    doc.edges.push({
      id: skId,
      measurement_edge_id: mid,
      relational_edge_id: mid,
      type,
      confirmed_length_ft: length,
      locked: length != null, // the measured length is authoritative; geometry must never overwrite it
      primary_facet_id: primarySketch,
      secondary_facet_id: secondarySketch,
      shared,
      v1: null, // never fabricated in this phase
      v2: null,
    });
    edgeMappings.push({ sketch_edge_id: skId, measurement_edge_id: mid });
    constraintLines.push({
      measurement_edge_id: mid, edge_type: type, length_ft: length,
      primary_facet_id: pMid, secondary_facet_id: sMid, shared,
    });
    // Record topology intent on the bordering planes (ids only — no ordering/geometry implied).
    [pMid, sMid].forEach((m) => {
      if (m != null && planeByMid[m]) {
        planeByMid[m].edge_ids.push(mid);
        const skf = doc.facets.find((x) => x.measurement_facet_id === m);
        if (skf) skf.edgeIds.push(skId);
      }
    });
    if (shared) adjacency.push({ measurement_edge_id: mid, edge_type: type, facets: [pMid, sMid] });
  }

  // ---- CANDIDATE PENETRATIONS (plane retained; XY NEVER fabricated) ---------------------------
  const penMappings = [];
  const constraintPens = [];
  for (const pen of scopedPens) {
    const mid = String(pen.id);
    const skId = sfid("msp", mid);
    const planeMid = String(pen.facet_id);
    const qty = num(pen.quantity);
    doc.penetrations.push({
      id: skId,
      measurement_penetration_id: mid,
      relational_penetration_id: mid,
      pen_type: pen.pen_type != null ? pen.pen_type : "other",
      quantity: qty != null ? qty : 1,
      measurement_facet_id: planeMid,
      x: null, y: null,           // unknown position — explicitly not fabricated
      position_known: false,
    });
    diag("info", "penetration_position_unknown", "penetration", mid,
      "Penetration is linked to a roof plane but has no known position; a location was not fabricated.");
    penMappings.push({ sketch_penetration_id: skId, measurement_penetration_id: mid, position_known: false });
    constraintPens.push({
      measurement_penetration_id: mid, pen_type: pen.pen_type != null ? pen.pen_type : "other",
      quantity: qty != null ? qty : 1, measurement_facet_id: planeMid, position_known: false,
    });
  }

  // Provenance so a later persistence layer can enforce "never overwrite an existing sketch".
  doc.generated = { source: "measurements", structure_id: structureId, generator_version: GENERATOR_VERSION, source_fingerprint };

  // ---- ARCHETYPE (high-level only; NO geometry laid out this phase) ---------------------------
  let archetype = "unknown";
  const planeCount = constraintPlanes.length;
  if (planeCount === 1) {
    archetype = "single_plane";
  } else if (planeCount === 2 && adjacency.length === 1 && adjacency[0].edge_type === "ridge") {
    archetype = "symmetric_gable";
  } else if (planeCount >= 2) {
    archetype = "complex";
  }

  // ---- STATUS / CONFIDENCE / UNRESOLVED -------------------------------------------------------
  const errors = diagnostics.filter((d) => d.severity === "error");
  const warnings = diagnostics.filter((d) => d.severity === "warning");
  const status = errors.length === 0 && planeCount > 0 ? "generated" : "needs_review";

  let confidence;
  if (status !== "generated") {
    confidence = "none";
    if (planeCount > 0) {
      diag("info", "geometry_deferred", "structure", structureId,
        "Relational candidate produced, but geometry layout is deferred until measurements are complete.");
    }
  } else if ((archetype === "single_plane" || archetype === "symmetric_gable") && warnings.length === 0) {
    confidence = "high";
    diag("info", "geometry_deferred", "structure", structureId,
      "Constraints are complete for a simple roof; geometry layout is deferred to a later phase.");
  } else if (archetype === "single_plane" || archetype === "symmetric_gable") {
    confidence = "medium";
    diag("info", "geometry_deferred", "structure", structureId,
      "Simple roof recognised with warnings; geometry layout is deferred to a later phase.");
  } else {
    confidence = "low";
    diag("info", "geometry_deferred_complex", "structure", structureId,
      "Roof topology is not a simple recognised type; geometry layout is deferred to a later phase.");
  }

  const unresolved = diagnostics.filter(
    (d) => d.severity === "error" || d.code === "geometry_deferred" || d.code === "geometry_deferred_complex",
  );

  return {
    ok: status === "generated",
    status,
    confidence,
    archetype,
    generator_version: GENERATOR_VERSION,
    structure_id: structureId,
    source_fingerprint,
    document: doc,
    constraints: {
      structure_id: structureId,
      planes: constraintPlanes,
      lines: constraintLines,
      penetrations: constraintPens,
      adjacency,
    },
    mappings: { facets: facetMappings, edges: edgeMappings, penetrations: penMappings },
    diagnostics,
    unresolved,
  };
}

module.exports = { generateProposedSketch, GENERATOR_VERSION, AREA_DIM_TOL };
