"use strict";
const assert = require("assert");
const { generateSketchGeometry, generateProposedSketch, validateSketch } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }

// ---- HIGH CONFIDENCE: a uniquely-constrained simple gable ---------------------------------------
function gable() {
  return {
    structure: { id: "S1" },
    facets: [
      { id: "FA", structure_id: "S1", facet_label: "Front", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 0 },
      { id: "FB", structure_id: "S1", facet_label: "Back", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 1 },
    ],
    edges: [{ id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 }],
    penetrations: [],
  };
}
let r = generateSketchGeometry(gable());
assert.strictEqual(r.readiness, "high_confidence"); ok("HIGH CONFIDENCE: gable readiness = high_confidence");
assert.strictEqual(r.partial, false); ok("high confidence: not partial");
assert.deepStrictEqual(r.resolved_planes.slice().sort(), ["FA", "FB"]); ok("high confidence: both planes resolved");
assert.deepStrictEqual(r.unresolved_planes, []); ok("high confidence: nothing unresolved");
assert.deepStrictEqual(r.ambiguities, []); ok("high confidence: no ambiguities");

// ---- NEEDS REVIEW: a valley pair — geometry could be proposed but the side is ambiguous ---------
function valleyPair() {
  return {
    structure: { id: "V" },
    facets: [
      { id: "F2", structure_id: "V", facet_label: "F2", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 0 },
      { id: "F5", structure_id: "V", facet_label: "F5", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 1 },
    ],
    edges: [
      { id: "VAL", edge_type: "valley", length_ft: 28, facet_id: "F2", facet_id_secondary: "F5", sort: 0 },
      { id: "E2", edge_type: "eave", length_ft: 20, facet_id: "F2", sort: 1 },
      { id: "E5", edge_type: "eave", length_ft: 20, facet_id: "F5", sort: 2 },
    ],
    penetrations: [],
  };
}
r = generateSketchGeometry(valleyPair());
assert.strictEqual(r.readiness, "needs_review"); ok("NEEDS REVIEW: valley pair readiness = needs_review");
assert.ok(r.ambiguities.length >= 1); ok("needs review: has ambiguity records");
const amb = r.ambiguities.find((a) => a.via_type === "valley");
assert.ok(amb && amb.plane === "F5" && amb.related_plane === "F2" && amb.via_edge === "VAL"); ok("needs review: ambiguity names the actual planes + roof line (F5/F2/VAL)");
assert.strictEqual(amb.message, "F5 placement needs review — measurements establish a Valley with F2 but do not uniquely establish which side of F2."); ok("needs review: human message matches the required example");
assert.strictEqual(r.document.vertices.length, 0); ok("needs review: no fabricated geometry");

// ---- INSUFFICIENT INFORMATION: a plane with no dimensions/pitch/area ------------------------------
function insufficient() {
  return { structure: { id: "S" }, facets: [{ id: "F1", structure_id: "S", facet_label: "F1", sort: 0 }], edges: [], penetrations: [] };
}
r = generateSketchGeometry(insufficient());
assert.strictEqual(r.readiness, "insufficient_information"); ok("INSUFFICIENT: no pitch/area/dims -> insufficient_information");
assert.strictEqual(r.document.vertices.length, 0); ok("insufficient: no geometry");
// a single plane with pitch+area but no W/L is also insufficient (cannot lay out boundary)
r = generateSketchGeometry({ structure: { id: "S" }, facets: [{ id: "F1", structure_id: "S", pitch_rise: 6, area_sqft: 500, facet_label: "F1", sort: 0 }], edges: [], penetrations: [] });
assert.strictEqual(r.readiness, "insufficient_information"); ok("insufficient: pitch+area but no width/length -> insufficient_information");

// ---- PARTIAL: a solvable gable section + an unresolvable valley section --------------------------
function partialRoof() {
  return {
    structure: { id: "P" },
    facets: [
      { id: "FA", structure_id: "P", facet_label: "FA", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 0 },
      { id: "FB", structure_id: "P", facet_label: "FB", pitch_rise: 6, area_sqft: 720, width_ft: 18, length_ft: 40, sort: 1 },
      { id: "FC", structure_id: "P", facet_label: "FC", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 2 },
      { id: "FD", structure_id: "P", facet_label: "FD", pitch_rise: 6, area_sqft: 400, width_ft: 20, length_ft: 20, sort: 3 },
    ],
    edges: [
      { id: "RIDGE", edge_type: "ridge", length_ft: 40, facet_id: "FA", facet_id_secondary: "FB", sort: 0 },
      { id: "VAL", edge_type: "valley", length_ft: 28, facet_id: "FC", facet_id_secondary: "FD", sort: 1 },
      { id: " EC", edge_type: "eave", length_ft: 20, facet_id: "FC", sort: 2 },
      { id: "ED", edge_type: "eave", length_ft: 20, facet_id: "FD", sort: 3 },
    ],
    penetrations: [],
  };
}
r = generateSketchGeometry(partialRoof());
assert.strictEqual(r.readiness, "needs_review"); ok("PARTIAL: readiness = needs_review");
assert.strictEqual(r.partial, true); ok("partial: partial = true");
assert.ok(r.document.vertices.length > 0); ok("partial: safe gable section IS drawn");
assert.strictEqual(validateSketch(r.document).valid, true); ok("partial: drawn section passes canonical validator");
assert.deepStrictEqual(r.resolved_planes.slice().sort(), ["FA", "FB"]); ok("partial: gable planes resolved");
assert.deepStrictEqual(r.unresolved_planes.slice().sort(), ["FC", "FD"]); ok("partial: valley planes explicitly unresolved");
assert.ok(r.ambiguities.some((a) => a.via_type === "valley" && a.plane === "FD")); ok("partial: unresolved valley section named in ambiguities");
assert.ok(r.diagnostics.some((d) => d.code === "partial_proposal")); ok("partial: partial_proposal diagnostic present");

// ---- CONTRADICTORY MEASUREMENTS (genuine geometric contradiction, not an Area override) --------
function contradictory() {
  const g = gable();
  g.edges[0].length_ft = 99; // ridge 99 while both planes are 18x40 -> neither dim matches the ridge
  return g;
}
r = generateSketchGeometry(contradictory());
assert.strictEqual(r.readiness, "needs_review"); ok("CONTRADICTORY: readiness = needs_review");
assert.ok(r.diagnostics.some((d) => d.code === "contradictory_dimensions")); ok("contradictory: diagnosed");
assert.strictEqual(r.document.vertices.length, 0); ok("contradictory: no geometry");

// ---- UNPOSITIONED PENETRATIONS -------------------------------------------------------------------
function penNoXY() {
  return {
    structure: { id: "S" },
    facets: [{ id: "F3", structure_id: "S", facet_label: "F3", pitch_rise: 4, area_sqft: 800, width_ft: 20, length_ft: 40, sort: 0 }],
    edges: [{ id: "E1", edge_type: "eave", length_ft: 40, facet_id: "F3", sort: 0 }],
    penetrations: [{ id: "PEN1", pen_type: "pipe_boot", quantity: 1, facet_id: "F3", sort: 0 }],
  };
}
r = generateSketchGeometry(penNoXY());
assert.strictEqual(r.readiness, "high_confidence"); ok("unpositioned pen: roof still high_confidence");
const p = r.document.penetrations.find((x) => x.measurement_penetration_id === "PEN1");
assert.strictEqual(p.measurement_facet_id, "F3"); ok("unpositioned pen: measurement relationship retained (F3)");
assert.strictEqual(p.x, null); assert.strictEqual(p.y, null); ok("unpositioned pen: NOT placed at center (x/y null)");
assert.strictEqual(p.position_known, false); ok("unpositioned pen: position_known = false");
assert.ok(r.diagnostics.some((d) => d.code === "penetration_position_unknown" && d.target_id === "PEN1")); ok("unpositioned pen: placement-required diagnostic present");

// ---- REPEAT-GENERATION STABILITY (no random flip/rotate) + source fingerprint --------------------
const s1 = JSON.stringify(generateSketchGeometry(gable()).document);
const s2 = JSON.stringify(generateSketchGeometry(gable()).document);
assert.strictEqual(s1, s2); ok("stability: identical measurements -> byte-identical geometry (no flip/rotate)");
const pShuf = partialRoof(); pShuf.facets.reverse(); pShuf.edges.reverse();
assert.strictEqual(JSON.stringify(generateSketchGeometry(pShuf).document), JSON.stringify(generateSketchGeometry(partialRoof()).document)); ok("stability: partial proposal stable regardless of input order");

// source fingerprint: same inputs -> same fingerprint; a changed measurement -> different fingerprint
const fpA = generateSketchGeometry(gable()).source_fingerprint;
const fpB = generateSketchGeometry(gable()).source_fingerprint;
assert.ok(fpA && fpA === fpB); ok("fingerprint: stable across runs for identical measurements");
const changed = gable(); changed.facets[0].pitch_rise = 8;
assert.notStrictEqual(generateSketchGeometry(changed).source_fingerprint, fpA); ok("fingerprint: changes when a measurement changes (change detection)");
assert.strictEqual(generateProposedSketch(gable()).source_fingerprint, fpA); ok("fingerprint: carried on the foundation result too");
// order of input records does NOT change the fingerprint (only values matter)
const gOrder = gable(); gOrder.facets.reverse();
assert.strictEqual(generateSketchGeometry(gOrder).source_fingerprint, fpA); ok("fingerprint: order-independent");

console.log("\nGENERATE SKETCH CONFIDENCE / AMBIGUITY / PARTIAL: all " + n + " assertions passed");
