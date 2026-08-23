/*
 * RoofSpan Mobile — Canvass Section client helpers (pure Node, no device).
 * Run: node src/tests/canvass.node.test.js
 */
const cv = require("../canvass");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

// cache keys are stable + section-scoped
ok(cv.CACHE_SECTIONS === "canvass_sections", "sections cache key stable");
ok(cv.propsCacheKey("abc") === "canvass_props_abc", "per-section property cache key");

// default section selection
ok(cv.pickDefaultSection([]) === null, "no sections -> null");
ok(cv.pickDefaultSection(null) === null, "null sections -> null");
ok(cv.pickDefaultSection([{ id: "s1" }, { id: "s2" }]) === "s1", "first assigned section chosen");

// polygon FeatureCollection shaping
const geo = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [0, 0]]] };
const fc = cv.buildSectionPolygonFC({ id: "s1", geometry: geo });
ok(fc.type === "FeatureCollection" && fc.features.length === 1, "section polygon FC built");
ok(fc.features[0].geometry === geo, "polygon geometry preserved");
ok(cv.buildSectionPolygonFC(null).features.length === 0, "no section -> empty FC");
ok(cv.buildSectionPolygonFC({ id: "s1" }).features.length === 0, "section without geometry -> empty FC");

// DNK color contract (red for DNK, brand otherwise)
ok(cv.pinColor(true, "#2563EB", "#DC2626") === "#DC2626", "DNK property renders red");
ok(cv.pinColor(false, "#2563EB", "#DC2626") === "#2563EB", "normal property renders brand color");

if (failures) { console.error(`\nCANVASS HELPERS: ${failures} failure(s)`); process.exit(1); }
console.log("\nCANVASS HELPERS: all passed");
