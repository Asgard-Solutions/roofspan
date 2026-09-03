"use strict";
const assert = require("assert");
const { generateProposedSketch, GENERATOR_VERSION } = require("..");

let n = 0;
function ok(name) { n++; console.log("  \u2713 " + name); }

// ---------------------------------------------------------------------------------------------
// Fixtures: a symmetric gable on structure ST1 (two planes sharing one ridge), one eave/rake per
// plane, one penetration on the front plane. Plus a foreign plane on ST2 to prove isolation.
// ---------------------------------------------------------------------------------------------
function gableInput() {
  return {
    structure: { id: "ST1", structure_type: "main_house" },
    facets: [
      { id: "MF1", structure_id: "ST1", facet_label: "Front", pitch_rise: 6, area_sqft: 600, width_ft: 30, length_ft: 20, orientation_azimuth: 180, roof_material: "shingle", sort: 0 },
      { id: "MF2", structure_id: "ST1", facet_label: "Back", pitch_rise: 6, area_sqft: 600, width_ft: 30, length_ft: 20, orientation_azimuth: 0, sort: 1 },
    ],
    edges: [
      { id: "ME_RIDGE", edge_type: "ridge", length_ft: 30, facet_id: "MF1", facet_id_secondary: "MF2", sort: 0 },
      { id: "ME_EAVE1", edge_type: "eave", length_ft: 30, facet_id: "MF1", sort: 1 },
      { id: "ME_EAVE2", edge_type: "eave", length_ft: 30, facet_id: "MF2", sort: 2 },
    ],
    penetrations: [
      { id: "MP1", pen_type: "pipe_boot", quantity: 2, facet_id: "MF1", sort: 0 },
    ],
  };
}

// --- happy path: symmetric gable -> generated, high confidence, correct relational mappings ---
const r = generateProposedSketch(gableInput());
assert.strictEqual(r.ok, true); ok("gable: ok = true");
assert.strictEqual(r.status, "generated"); ok("gable: status = generated");
assert.strictEqual(r.archetype, "symmetric_gable"); ok("gable: archetype = symmetric_gable");
assert.strictEqual(r.confidence, "high"); ok("gable: confidence = high");
assert.strictEqual(r.generator_version, GENERATOR_VERSION); ok("gable: carries generator version");

// --- relational identity: sketch ids derive from measurement ids; mappings are exact ------------
assert.deepStrictEqual(r.mappings.facets.map((m) => m.measurement_facet_id).sort(), ["MF1", "MF2"]); ok("facet mappings cover MF1/MF2");
const mf1 = r.document.facets.find((f) => f.measurement_facet_id === "MF1");
assert.ok(mf1 && mf1.relational_facet_id === "MF1"); ok("sketch facet retains relational_facet_id");
assert.strictEqual(mf1.pitch_rise, 6); ok("carries pitch");
assert.strictEqual(mf1.confirmed_area_sqft, 600); ok("carries confirmed area");
assert.strictEqual(mf1.label, "Front"); ok("carries label");
assert.strictEqual(mf1.orientation_azimuth, 180); ok("carries orientation azimuth");
assert.deepStrictEqual(mf1.vertexIds, []); ok("facet has NO fabricated vertices");

const ridge = r.document.edges.find((e) => e.measurement_edge_id === "ME_RIDGE");
assert.ok(ridge && ridge.relational_edge_id === "ME_RIDGE"); ok("sketch edge retains relational_edge_id");
assert.strictEqual(ridge.type, "ridge"); ok("carries edge classification");
assert.strictEqual(ridge.confirmed_length_ft, 30); ok("carries confirmed edge length");
assert.strictEqual(ridge.locked, true); ok("measured edge marked locked (authoritative)");
assert.strictEqual(ridge.shared, true); ok("ridge marked shared (two planes)");
assert.strictEqual(ridge.primary_facet_id, mf1.id); ok("ridge primary plane -> MF1 sketch id");
assert.strictEqual(ridge.secondary_facet_id, r.document.facets.find((f) => f.measurement_facet_id === "MF2").id); ok("ridge secondary plane -> MF2 sketch id");
assert.strictEqual(ridge.v1, null); assert.strictEqual(ridge.v2, null); ok("edge has NO fabricated endpoints");

// adjacency (constraint/topology representation) reflects the shared ridge only
assert.strictEqual(r.constraints.adjacency.length, 1); ok("one shared-edge adjacency recorded");
assert.deepStrictEqual(r.constraints.adjacency[0].facets.sort(), ["MF1", "MF2"]); ok("adjacency links MF1<->MF2 by id");

// scale stays unresolved (no geometry invented)
assert.strictEqual(r.document.scale.resolved, false); ok("scale stays unresolved (no invented geometry)");
assert.deepStrictEqual(r.document.vertices, []); ok("document has zero vertices");
assert.strictEqual(r.document.generated.source, "measurements"); ok("provenance stamped for no-overwrite enforcement");

// --- unknown penetration position is NOT fabricated -------------------------------------------
const p = r.document.penetrations.find((x) => x.measurement_penetration_id === "MP1");
assert.ok(p, "penetration candidate exists");
assert.strictEqual(p.x, null); assert.strictEqual(p.y, null); ok("penetration XY not fabricated (null)");
assert.strictEqual(p.position_known, false); ok("penetration position_known = false");
assert.strictEqual(p.measurement_facet_id, "MF1"); ok("penetration retains its roof plane relation");
assert.ok(r.diagnostics.some((d) => d.code === "penetration_position_unknown" && d.target_id === "MP1")); ok("diagnostic: penetration position unknown");

// --- STRUCTURE ISOLATION: a foreign plane/edge/pen never leaks into the candidate --------------
const iso = gableInput();
iso.facets.push({ id: "MF_OTHER", structure_id: "ST2", facet_label: "OtherHouse", pitch_rise: 5, area_sqft: 999, sort: 9 });
iso.edges.push({ id: "ME_OTHER", edge_type: "eave", length_ft: 40, facet_id: "MF_OTHER", sort: 9 });
iso.penetrations.push({ id: "MP_OTHER", pen_type: "chimney", quantity: 1, facet_id: "MF_OTHER", sort: 9 });
const ri = generateProposedSketch(iso);
assert.ok(!ri.document.facets.some((f) => f.measurement_facet_id === "MF_OTHER")); ok("isolation: foreign plane excluded");
assert.ok(!ri.document.edges.some((e) => e.measurement_edge_id === "ME_OTHER")); ok("isolation: foreign edge excluded");
assert.ok(!ri.document.penetrations.some((x) => x.measurement_penetration_id === "MP_OTHER")); ok("isolation: foreign penetration excluded");
assert.ok(ri.diagnostics.some((d) => d.code === "foreign_facet" && d.target_id === "MF_OTHER")); ok("isolation: foreign plane diagnosed");
assert.ok(ri.diagnostics.some((d) => d.code === "foreign_edge" && d.target_id === "ME_OTHER")); ok("isolation: foreign edge diagnosed");
assert.strictEqual(ri.mappings.facets.length, 2); ok("isolation: only in-structure planes mapped");

// --- NO FUZZY MATCHING: identical type+length edges keep their own ids; relations by id only ---
const fuzzy = {
  structure: { id: "S", },
  facets: [
    { id: "FA", structure_id: "S", facet_label: "A", pitch_rise: 6, area_sqft: 100, sort: 0 },
    { id: "FB", structure_id: "S", facet_label: "A", pitch_rise: 6, area_sqft: 100, sort: 1 }, // SAME label/pitch/area
  ],
  edges: [
    { id: "EA", edge_type: "eave", length_ft: 25, facet_id: "FA", sort: 0 },
    { id: "EB", edge_type: "eave", length_ft: 25, facet_id: "FB", sort: 1 }, // SAME type/length as EA
  ],
  penetrations: [],
};
const rf = generateProposedSketch(fuzzy);
const ea = rf.document.edges.find((e) => e.measurement_edge_id === "EA");
const eb = rf.document.edges.find((e) => e.measurement_edge_id === "EB");
assert.ok(ea && eb && ea.id !== eb.id); ok("no-fuzzy: identical edges keep distinct ids");
assert.strictEqual(ea.primary_facet_id, rf.document.facets.find((f) => f.measurement_facet_id === "FA").id); ok("no-fuzzy: EA -> FA by id");
assert.strictEqual(eb.primary_facet_id, rf.document.facets.find((f) => f.measurement_facet_id === "FB").id); ok("no-fuzzy: EB -> FB by id (not merged by identical attrs)");

// --- DETERMINISM: identical input -> identical logical proposal (stable regardless of input order)
const a1 = generateProposedSketch(gableInput());
const shuffled = gableInput();
shuffled.facets.reverse(); shuffled.edges.reverse(); // reorder input arrays
const a2 = generateProposedSketch(shuffled);
assert.deepStrictEqual(a2.document.facets, a1.document.facets); ok("determinism: facets identical regardless of input order");
assert.deepStrictEqual(a2.document.edges, a1.document.edges); ok("determinism: edges identical regardless of input order");
assert.deepStrictEqual(a2.mappings, a1.mappings); ok("determinism: mappings identical");
assert.deepStrictEqual(a2.constraints, a1.constraints); ok("determinism: constraint representation identical");
assert.strictEqual(JSON.stringify(a1), JSON.stringify(generateProposedSketch(gableInput()))); ok("determinism: full result byte-identical on repeat");

// --- MISSING INFORMATION -> diagnostics, not guesses ------------------------------------------
const missing = {
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", facet_label: "F1", pitch_rise: null, area_sqft: 0, sort: 0 }],
  edges: [{ id: "E1", edge_type: "eave", length_ft: 0, facet_id: "F1", sort: 0 }],
  penetrations: [],
};
const rm = generateProposedSketch(missing);
assert.strictEqual(rm.ok, false); ok("missing: ok = false");
assert.strictEqual(rm.status, "needs_review"); ok("missing: status = needs_review");
assert.strictEqual(rm.confidence, "none"); ok("missing: confidence = none");
assert.ok(rm.diagnostics.some((d) => d.code === "missing_pitch" && d.severity === "error")); ok("missing: pitch diagnosed as error");
assert.ok(rm.diagnostics.some((d) => d.code === "missing_area" && d.severity === "error")); ok("missing: area diagnosed as error");
assert.ok(rm.unresolved.some((d) => d.code === "missing_pitch")); ok("missing: pitch is in unresolved");

// no planes at all -> needs_review with no_roof_planes
const empty = generateProposedSketch({ structure: { id: "S" }, facets: [], edges: [], penetrations: [] });
assert.strictEqual(empty.status, "needs_review"); ok("empty: needs_review");
assert.ok(empty.diagnostics.some((d) => d.code === "no_roof_planes")); ok("empty: no_roof_planes diagnostic");

// missing structure entirely -> error, never throws
const noStruct = generateProposedSketch({ facets: [], edges: [], penetrations: [] });
assert.strictEqual(noStruct.status, "needs_review"); ok("no-structure: needs_review (no throw)");
assert.ok(noStruct.diagnostics.some((d) => d.code === "missing_structure")); ok("no-structure: diagnosed");

// --- unassigned edge / penetration are reported, not silently placed --------------------------
const orphan = {
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", facet_label: "F1", pitch_rise: 6, area_sqft: 400, sort: 0 }],
  edges: [{ id: "E_ORPH", edge_type: "eave", length_ft: 20, sort: 0 }], // no facet link
  penetrations: [{ id: "P_ORPH", pen_type: "pipe_boot", quantity: 1, sort: 0 }], // no facet link
};
const ro = generateProposedSketch(orphan);
assert.ok(!ro.document.edges.some((e) => e.measurement_edge_id === "E_ORPH")); ok("orphan edge excluded from candidate");
assert.ok(ro.diagnostics.some((d) => d.code === "edge_unassigned")); ok("orphan edge diagnosed");
assert.ok(!ro.document.penetrations.some((x) => x.measurement_penetration_id === "P_ORPH")); ok("orphan penetration excluded");
assert.ok(ro.diagnostics.some((d) => d.code === "penetration_unassigned")); ok("orphan penetration diagnosed");

// --- single plane archetype -------------------------------------------------------------------
const single = {
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", facet_label: "Shed", pitch_rise: 3, area_sqft: 300, width_ft: 15, length_ft: 20, sort: 0 }],
  edges: [{ id: "E1", edge_type: "eave", length_ft: 20, facet_id: "F1", sort: 0 }],
  penetrations: [],
};
const rs = generateProposedSketch(single);
assert.strictEqual(rs.archetype, "single_plane"); ok("single plane archetype");
assert.strictEqual(rs.confidence, "high"); ok("single plane high confidence");
// width*length (300) == area (300) -> no mismatch diagnostic
assert.ok(!rs.diagnostics.some((d) => d.code === "area_dimension_mismatch")); ok("consistent area/dims -> no mismatch diagnostic");

// --- area vs width*length mismatch is an INFO diagnostic, area kept authoritative --------------
const mism = {
  structure: { id: "S" },
  facets: [{ id: "F1", structure_id: "S", facet_label: "F1", pitch_rise: 6, area_sqft: 700, width_ft: 10, length_ft: 8, sort: 0 }],
  edges: [{ id: "E1", edge_type: "eave", length_ft: 10, facet_id: "F1", sort: 0 }],
  penetrations: [],
};
const rmm = generateProposedSketch(mism);
assert.ok(rmm.diagnostics.some((d) => d.code === "area_dimension_mismatch" && d.severity === "info")); ok("area/dim mismatch -> info diagnostic");
assert.strictEqual(rmm.document.facets[0].confirmed_area_sqft, 700); ok("confirmed area kept authoritative on mismatch");
assert.strictEqual(rmm.confidence, "high"); ok("info-only mismatch does not lower confidence");

console.log("\nGENERATE SKETCH FOUNDATION: all " + n + " assertions passed");
