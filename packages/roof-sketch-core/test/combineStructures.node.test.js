"use strict";
// position_offset_ft (pin a cross-gable wing) + combineStructuresSitePlan (unified multi-structure plan).
// Run: node packages/roof-sketch-core/test/combineStructures.node.test.js
const assert = require("assert");
const { generateProposedSketch } = require("../generateSketch");
const { frameRoof } = require("../frameRoof");
const { combineStructuresSitePlan } = require("../combineStructures");
const { validateSketch } = require("../topology");

let n = 0; const ok = (m) => { n++; console.log("  ok -", m); };
const build = (fx) => frameRoof(generateProposedSketch(fx), fx.edges, null);
console.log("COMBINE + OFFSET:");

// ---- (1) position_offset_ft pins a projecting cross-gable wing along the host wall ----------------
const ST = { id: "ST", name: "House" };
function crossGable(offset) {
  return {
    structure: ST,
    facets: [
      { id: "M1", structure_id: "ST", label: "M1", pitch_rise: 6, width_ft: 11.18, length_ft: 48, area_sqft: 500, sort: 1 },
      { id: "M2", structure_id: "ST", label: "M2", pitch_rise: 6, width_ft: 11.18, length_ft: 48, area_sqft: 500, sort: 2 },
      { id: "G1", structure_id: "ST", label: "G1", pitch_rise: 6, width_ft: 10.06, length_ft: 16, area_sqft: 160, sort: 3, position_offset_ft: offset },
      { id: "G2", structure_id: "ST", label: "G2", pitch_rise: 6, width_ft: 10.06, length_ft: 16, area_sqft: 160, sort: 4 },
    ],
    edges: [
      { id: "RM", structure_id: "ST", edge_type: "ridge", length_ft: 48, facet_id: "M1", facet_id_secondary: "M2", sort: 1 },
      { id: "RG", structure_id: "ST", edge_type: "ridge", length_ft: 16, facet_id: "G1", facet_id_secondary: "G2", sort: 2 },
      { id: "VL", structure_id: "ST", edge_type: "valley", length_ft: 13, facet_id: "M1", facet_id_secondary: "G1", sort: 3 },
      { id: "VR", structure_id: "ST", edge_type: "valley", length_ft: 13, facet_id: "M1", facet_id_secondary: "G2", sort: 4 },
      { id: "EM1", structure_id: "ST", edge_type: "eave", length_ft: 48, facet_id: "M1", sort: 5 },
      { id: "EM2", structure_id: "ST", edge_type: "eave", length_ft: 48, facet_id: "M2", sort: 6 },
      { id: "EG1", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "G1", sort: 7 },
      { id: "EG2", structure_id: "ST", edge_type: "eave", length_ft: 16, facet_id: "G2", sort: 8 },
    ],
    penetrations: [],
  };
}
// The wing apex on the host slope sits at (cx, hg=~9). Default (no offset) centres at cx=24; a
// position_offset_ft=14 must move the apex to x≈14.
const def = build(crossGable(null));
const pin = build(crossGable(14));
assert.strictEqual(pin.method, "cross_gable", "offset: still solved as a cross-gable");
const apex = (doc) => doc.vertices.filter((v) => Math.abs(v.y - 9) < 1.2).map((v) => v.x).sort((a, b) => a - b);
const defApex = apex(def.doc), pinApex = apex(pin.doc);
assert.ok(defApex.some((x) => Math.abs(x - 24) < 1.0), `offset: default wing centred (apex x≈24, got ${defApex})`);
assert.ok(pinApex.some((x) => Math.abs(x - 14) < 1.0), `offset: pinned wing apex x≈14 (got ${pinApex})`);
// Pinning removes the "position approximate" warning for that wing.
assert.ok(!(pin.approximations || []).some((a) => a.code === "approx_wing_position"), "offset: pinned wing is not flagged approximate");
assert.ok((def.approximations || []).some((a) => a.code === "approx_wing_position"), "offset: unpinned wing IS flagged approximate");
ok("position_offset_ft pins a cross-gable wing exactly along the host wall (and clears the approximate flag)");

// ---- (2) combineStructuresSitePlan: side-by-side, largest first, offsets adjustable --------------
const HOUSE_F = [
  { id: "F1", structure_id: "H", label: "F1", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 1 },
  { id: "F2", structure_id: "H", label: "F2", pitch_rise: 6, width_ft: 20, length_ft: 40, area_sqft: 800, sort: 2 },
];
const HOUSE_E = [
  { id: "RH", structure_id: "H", edge_type: "ridge", length_ft: 40, facet_id: "F1", facet_id_secondary: "F2", sort: 1 },
  { id: "EH1", structure_id: "H", edge_type: "eave", length_ft: 40, facet_id: "F1", sort: 2 },
  { id: "EH2", structure_id: "H", edge_type: "eave", length_ft: 40, facet_id: "F2", sort: 3 },
];
const GAR_F = [
  { id: "G1", structure_id: "G", label: "G1", pitch_rise: 6, width_ft: 10, length_ft: 24, area_sqft: 240, sort: 1 },
  { id: "G2", structure_id: "G", label: "G2", pitch_rise: 6, width_ft: 10, length_ft: 24, area_sqft: 240, sort: 2 },
];
const GAR_E = [
  { id: "RG2", structure_id: "G", edge_type: "ridge", length_ft: 24, facet_id: "G1", facet_id_secondary: "G2", sort: 1 },
  { id: "EG1x", structure_id: "G", edge_type: "eave", length_ft: 24, facet_id: "G1", sort: 2 },
  { id: "EG2x", structure_id: "G", edge_type: "eave", length_ft: 24, facet_id: "G2", sort: 3 },
];
const combineInput = (offsets) => ({
  structures: [
    { id: "G", name: "Garage", structure_type: "attached_garage", included_in_scope: true, sort: 1 },
    { id: "H", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 },
    { id: "X", name: "Shed", structure_type: "shed", included_in_scope: false, sort: 2 },
  ],
  facets: [...HOUSE_F, ...GAR_F, { id: "X1", structure_id: "X", label: "X1", pitch_rise: 6, width_ft: 8, length_ft: 10, area_sqft: 80, sort: 1 }],
  edges: [...HOUSE_E, ...GAR_E],
  penetrations: [],
  offsets: offsets || {},
});

const res = combineStructuresSitePlan(combineInput());
assert.strictEqual(res.ok, true, "combine: produced a plan");
assert.strictEqual(res.placed_count, 2, "combine: exactly the two in-scope structures placed (shed excluded)");
assert.strictEqual(res.placements[0].label, "House", "combine: largest structure (House) placed first");
assert.strictEqual(res.placements[1].label, "Garage", "combine: garage placed second");
// Structures do not overlap: garage starts to the right of the house + gap.
const h = res.placements[0], g = res.placements[1];
assert.ok(g.bbox.x >= h.bbox.x + h.bbox.width + 12 - 0.01, `combine: garage sits right of house with the gap (h.right=${h.bbox.x + h.bbox.width}, g.x=${g.bbox.x})`);
// Every combined facet carries its structure id; no out-of-scope structure appears.
assert.ok(res.document.facets.every((f) => f.structure_id === "H" || f.structure_id === "G"), "combine: every facet tagged to an in-scope structure");
assert.ok(!res.document.facets.some((f) => f.structure_id === "X"), "combine: out-of-scope shed excluded");
// Vertex ids are globally unique across the merged structures.
const vids = res.document.vertices.map((v) => v.id);
assert.strictEqual(new Set(vids).size, vids.length, "combine: vertex ids are unique across structures");
// Aligned to a common top (min y == 0).
assert.ok(Math.abs(Math.min(...res.document.vertices.map((v) => v.y))) < 0.01, "combine: structures aligned to a common top edge");
ok("combineStructuresSitePlan lays in-scope structures side-by-side, largest first, non-overlapping, uniquely-ided");

// Deterministic: same input => byte-identical placements.
assert.deepStrictEqual(combineStructuresSitePlan(combineInput()).placements, res.placements, "combine: deterministic placements");

// Offsets nudge a structure and are honoured.
const shifted = combineStructuresSitePlan(combineInput({ G: { dx: 7, dy: -3 } }));
const g2 = shifted.placements.find((p) => p.label === "Garage");
assert.ok(Math.abs((g2.tx - g.tx) - 7) < 0.01, "combine: dx offset shifts the garage by +7 ft");
assert.ok(Math.abs((g2.ty - g.ty) - (-3)) < 0.01, "combine: dy offset shifts the garage by -3 ft");
ok("combineStructuresSitePlan honours per-structure drag offsets deterministically");

console.log(`\nCOMBINE + OFFSET: ${n} assertions passed.`);
