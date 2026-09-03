"use strict";
// Compare a CURRENT sketch document against a freshly generated PROPOSAL result, by RELATIONAL identity
// only (measurement_facet_id / measurement_edge_id — never client sketch ids or label/length matching).
// Pure/deterministic. Surfaces meaningful differences for an Office review UI. It does NOT merge graphs
// and never mutates either document.
const AREA_TOL = 0.5;
const LEN_TOL = 0.5;

const numOrNull = (v) => (v == null || v === "" ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

// Relational view of a document keyed by measurement ids (manual/unmapped geometry is counted separately).
function _relView(doc) {
  const d = doc || {};
  const edgeMidById = {};
  (d.edges || []).forEach((e) => { if (e && e.measurement_edge_id != null) edgeMidById[e.id] = String(e.measurement_edge_id); });
  const planes = {};
  (d.facets || []).forEach((f) => {
    if (!f || f.measurement_facet_id == null) return;
    const mid = String(f.measurement_facet_id);
    const edgeMids = (f.edgeIds || []).map((id) => edgeMidById[id]).filter(Boolean).sort();
    planes[mid] = { mid, pitch: numOrNull(f.pitch_rise), area: numOrNull(f.confirmed_area_sqft), edgeMids };
  });
  const lines = {};
  (d.edges || []).forEach((e) => {
    if (!e || e.measurement_edge_id == null) return;
    const mid = String(e.measurement_edge_id);
    lines[mid] = { mid, type: e.type != null ? e.type : null, length: numOrNull(e.confirmed_length_ft), shared: !!(e.primary_facet_id && e.secondary_facet_id) };
  });
  const unmappedFacets = (d.facets || []).filter((f) => f && f.measurement_facet_id == null).length;
  return { planes, lines, unmappedFacets };
}

function compareSketchProposal(currentDoc, proposalResult) {
  const proposedDoc = (proposalResult && proposalResult.document) || {};
  const cur = _relView(currentDoc);
  const pro = _relView(proposedDoc);
  const differences = [];
  const add = (code, target_type, target_id, detail) => differences.push({ code, target_type, target_id: target_id != null ? String(target_id) : null, detail });

  // ---- planes (Roof Planes) ----
  const curP = Object.keys(cur.planes), proP = Object.keys(pro.planes);
  const added_planes = proP.filter((m) => !cur.planes[m]).sort();
  const removed_planes = curP.filter((m) => !pro.planes[m]).sort();
  const changed_planes = [];
  proP.filter((m) => cur.planes[m]).sort().forEach((m) => {
    const a = cur.planes[m], b = pro.planes[m];
    const changes = [];
    if (a.pitch !== b.pitch) changes.push("pitch");
    if (a.area != null && b.area != null && Math.abs(a.area - b.area) > AREA_TOL) changes.push("area");
    else if ((a.area == null) !== (b.area == null)) changes.push("area");
    if (a.edgeMids.join("|") !== b.edgeMids.join("|")) changes.push("topology");
    if (changes.length) { changed_planes.push({ measurement_facet_id: m, changes }); changes.forEach((c) => add(`plane_${c}_changed`, "facet", m, `${a[c === "topology" ? "edgeMids" : c]} -> ${b[c === "topology" ? "edgeMids" : c]}`)); }
  });
  added_planes.forEach((m) => add("plane_added", "facet", m, "present in proposal, not in current sketch"));
  removed_planes.forEach((m) => add("plane_removed", "facet", m, "present in current sketch, not in proposal"));

  // ---- roof lines ----
  const curL = Object.keys(cur.lines), proL = Object.keys(pro.lines);
  const added_lines = proL.filter((m) => !cur.lines[m]).sort();
  const removed_lines = curL.filter((m) => !pro.lines[m]).sort();
  const changed_lines = [];
  proL.filter((m) => cur.lines[m]).sort().forEach((m) => {
    const a = cur.lines[m], b = pro.lines[m];
    const changes = [];
    if (a.type !== b.type) changes.push("type");
    if (a.length != null && b.length != null && Math.abs(a.length - b.length) > LEN_TOL) changes.push("length");
    else if ((a.length == null) !== (b.length == null)) changes.push("length");
    if (a.shared !== b.shared) changes.push("topology");
    if (changes.length) { changed_lines.push({ measurement_edge_id: m, changes }); changes.forEach((c) => add(`line_${c}_changed`, "edge", m, changes.join(","))); }
  });
  added_lines.forEach((m) => add("line_added", "edge", m, "present in proposal, not in current sketch"));
  removed_lines.forEach((m) => add("line_removed", "edge", m, "present in current sketch, not in proposal"));

  // ---- manual/unmapped current geometry (a proposal cannot represent it) ----
  if (cur.unmappedFacets > 0) add("unmapped_current_geometry", "structure", null, `${cur.unmappedFacets} current facet(s) are not mapped to Measurements and would be lost if replaced`);

  // ---- unresolved areas carried from the proposal ----
  const unresolved_planes = (proposalResult && proposalResult.unresolved_planes) || [];
  const ambiguities = (proposalResult && proposalResult.ambiguities) || [];
  unresolved_planes.forEach((m) => add("unresolved_in_proposal", "facet", m, "proposal could not resolve this roof plane"));
  ambiguities.forEach((amb) => add("ambiguity_in_proposal", amb.plane != null ? "facet" : "structure", amb.plane != null ? amb.plane : null, amb.message));

  const identical = added_planes.length === 0 && removed_planes.length === 0 && changed_planes.length === 0 &&
    added_lines.length === 0 && removed_lines.length === 0 && changed_lines.length === 0 &&
    cur.unmappedFacets === 0 && (proposalResult && proposalResult.readiness) === "high_confidence";

  return {
    identical,
    readiness: (proposalResult && proposalResult.readiness) || "insufficient_information",
    proposal_has_geometry: (proposedDoc.vertices || []).length > 0,
    added_planes, removed_planes, changed_planes,
    added_lines, removed_lines, changed_lines,
    unmapped_current_facets: cur.unmappedFacets,
    unresolved_planes, ambiguities,
    differences,
  };
}

module.exports = { compareSketchProposal };
