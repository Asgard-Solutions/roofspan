"use strict";
// Verifies the RoofThumbnail data pipeline: generateSketchGeometry -> resolveFacetBoundary -> points.
const assert = require("assert");
const { generateSketchGeometry, resolveFacetBoundary } = require("/app/packages/roof-sketch-core");

function thumbView(input) {
  const res = generateSketchGeometry(input);
  const doc = res && res.document;
  if (!doc || !(doc.vertices || []).length || !(doc.facets || []).length) return { status: "unavailable" };
  const polys = doc.facets.map((f) => (resolveFacetBoundary(doc, f).points || [])).filter((p) => p.length >= 3);
  const lines = doc.edges.map((e) => e.type);
  return { status: "ok", polys, lines, readiness: res.readiness };
}

const ST = { id: "ST" };
const LROOF = { structure: ST, facets: [
  { id: "F1", structure_id: "ST", label: "F1", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 300 },
  { id: "F2", structure_id: "ST", label: "F2", pitch_rise: 6, width_ft: 11.18, length_ft: 40, area_sqft: 200 },
  { id: "F3", structure_id: "ST", label: "F3", pitch_rise: 6, width_ft: 11.18, length_ft: 30, area_sqft: 250 },
  { id: "F4", structure_id: "ST", label: "F4", pitch_rise: 6, width_ft: 11.18, length_ft: 30, area_sqft: 150 },
], edges: [
  { id: "RH", edge_type: "ridge", length_ft: 30, facet_id: "F1", facet_id_secondary: "F2" },
  { id: "RV", edge_type: "ridge", length_ft: 20, facet_id: "F3", facet_id_secondary: "F4" },
  { id: "HIP", edge_type: "hip", length_ft: 14, facet_id: "F1", facet_id_secondary: "F3" },
  { id: "VAL", edge_type: "valley", length_ft: 14, facet_id: "F2", facet_id_secondary: "F4" },
  { id: "E1", edge_type: "eave", length_ft: 40, facet_id: "F1" }, { id: "E2", edge_type: "eave", length_ft: 20, facet_id: "F2" },
  { id: "E3", edge_type: "eave", length_ft: 30, facet_id: "F3" }, { id: "E4", edge_type: "eave", length_ft: 10, facet_id: "F4" },
], penetrations: [] };

const v = thumbView(LROOF);
assert.strictEqual(v.status, "ok", "L-roof thumbnail renders");
assert.strictEqual(v.polys.length, 4, "L-roof thumbnail: 4 facet polygons with >=3 points");
assert.ok(v.lines.includes("hip") && v.lines.includes("valley") && v.lines.includes("ridge"), "L-roof thumbnail: hip/valley/ridge lines present");
v.polys.forEach((p, i) => assert.ok(p.every((pt) => Number.isFinite(pt[0]) && Number.isFinite(pt[1])), `poly ${i} finite`));

// Insufficient measurements -> preview unavailable (component shows a placeholder, never crashes).
const bare = thumbView({ structure: ST, facets: [{ id: "X", structure_id: "ST", label: "X" }], edges: [], penetrations: [] });
assert.notStrictEqual(bare.status, "ok", "bare structure -> no preview (placeholder)");

console.log("RoofThumbnail pipeline: L-roof ->", v.polys.length, "polys,", new Set(v.lines).size, "line types (", v.readiness, "); bare ->", bare.status);
console.log("PASS");
