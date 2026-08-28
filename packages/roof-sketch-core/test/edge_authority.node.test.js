"use strict";
// Foundation closure: connected_graph requires authoritative edgeIds; proposals use the SAME
// authoritative boundary (edge loop for connected, vertexIds for manual).
const assert = require("assert");
const { createSketchDocument, validateSketch, deriveProposals } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }
const has = (list, code) => list.map((x) => x.code).includes(code);
const RESOLVED = { resolved: true, feetPerUnit: 1, feet_per_unit: 1, method: "structure_calibration" };

// A 10x10 square described by an ordered edge loop (no redundant vertexIds).
function connectedSquare({ vertexIds = null } = {}) {
  const d = createSketchDocument({ structureId: "s1" }); // edit_mode defaults to connected_graph
  d.scale = { ...RESOLVED };
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 10 }, { id: "v4", x: 0, y: 10 }];
  d.edges = [
    { id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" },
    { id: "e3", v1: "v3", v2: "v4" }, { id: "e4", v1: "v4", v2: "v1" }];
  const f = { id: "f1", edgeIds: ["e1", "e2", "e3", "e4"], pitch_rise: 0 };
  if (vertexIds) f.vertexIds = vertexIds;
  d.facets = [f];
  return d;
}

// --- ITEM 2: connected_graph facet WITHOUT edgeIds is a HARD error (no vertex-only fallback) ---
{
  const d = createSketchDocument({ structureId: "s1" });
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 10 }, { id: "v4", x: 0, y: 10 }];
  d.facets = [{ id: "f1", vertexIds: ["v1", "v2", "v3", "v4"] }]; // vertex-only in connected mode
  const v = validateSketch(d);
  assert.ok(has(v.errors, "facet_missing_edges")); ok("connected + no edgeIds => facet_missing_edges is a HARD ERROR");
  assert.strictEqual(v.valid, false); ok("connected vertex-only facet is INVALID (no silent fallback)");
  assert.ok(!has(v.warnings, "facet_missing_edges")); ok("facet_missing_edges is not merely a warning");
}

// --- ITEM 3a: connected facet with edgeIds and NO vertexIds -> valid + correct area proposal ---
{
  const d = connectedSquare();
  const v = validateSketch(d);
  assert.strictEqual(v.valid, true); ok("connected facet with edgeIds and no vertexIds is valid");
  const props = deriveProposals(d);
  const area = props.find((p) => p.code === "facet_area" && p.target_id === "f1");
  assert.ok(area, "a facet_area proposal must be generated from the edge loop");
  assert.strictEqual(area.proposed, 100); ok("edge-loop area proposal computed correctly (100 sqft) with no vertexIds");
}

// --- ITEM 3b: contradictory vertexIds -> validation fails AND proposals do NOT use vertexIds ---
{
  const d = connectedSquare({ vertexIds: ["v1", "v3", "v2", "v4"] }); // a different (bowtie) cycle
  const v = validateSketch(d);
  assert.ok(has(v.errors, "facet_boundary_mismatch")); ok("contradictory vertexIds => facet_boundary_mismatch");
  assert.strictEqual(v.valid, false); ok("contradictory connected facet is invalid");
  const props = deriveProposals(d);
  assert.ok(!props.some((p) => p.code === "facet_area" && p.target_id === "f1"),
    "no facet_area proposal may be produced from the contradictory vertex boundary");
  ok("proposal engine skips the contradictory facet (never uses the wrong vertexIds)");
}

// --- ITEM 3c: manual polygon still derives area from vertexIds ---
{
  const d = createSketchDocument({ structureId: "s1", editMode: "manual_polygon" });
  d.scale = { ...RESOLVED };
  d.vertices = [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 10 }, { id: "v4", x: 0, y: 10 }];
  d.facets = [{ id: "fm", vertexIds: ["v1", "v2", "v3", "v4"], pitch_rise: 0 }];
  const v = validateSketch(d);
  assert.strictEqual(v.valid, true); ok("manual polygon with vertexIds is valid");
  const area = deriveProposals(d).find((p) => p.code === "facet_area" && p.target_id === "fm");
  assert.ok(area && area.proposed === 100); ok("manual polygon area proposal derived from vertexIds (100 sqft)");
}

console.log("\nEDGE AUTHORITY + PROPOSALS: all " + n + " assertions passed");
