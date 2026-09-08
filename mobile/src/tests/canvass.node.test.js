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

// Pin color contract (red for DNK, brand otherwise)
ok(cv.pinColor(true, "#2563EB", "#DC2626") === "#DC2626", "DNK property renders red");
ok(cv.pinColor(false, "#2563EB", "#DC2626") === "#2563EB", "normal property renders brand color");

// ---------- Phase 4: buildAllSectionsFC — ALL assigned sections rendered together ----------
const g1 = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [0, 0]]] };
const g2 = { type: "Polygon", coordinates: [[[2, 2], [2, 3], [3, 3], [2, 2]]] };
const g3 = { type: "Polygon", coordinates: [[[4, 4], [4, 5], [5, 5], [4, 4]]] };
const secs3 = [
  { id: "sA", name: "Alpha", color: "#f00", geometry: g1 },
  { id: "sB", name: "Beta",  color: "#0f0", geometry: g2 },
  { id: "sC", name: "Gamma", color: "#00f", geometry: g3 },
];

// Three assigned sections => three polygon features, one per section, in order.
const fcAll = cv.buildAllSectionsFC(secs3, "sB");
ok(fcAll.type === "FeatureCollection", "buildAllSectionsFC returns a FeatureCollection");
ok(fcAll.features.length === 3, "three assigned sections => three polygon features");
ok(fcAll.features.every((f) => f.type === "Feature"), "each entry is a Feature");
ok(fcAll.features.every((f) => f.geometry && f.geometry.type === "Polygon"),
   "each feature carries the section polygon geometry");

// Each feature.properties has section_id, name, color, selected (only sB is selected).
const propsById = Object.fromEntries(fcAll.features.map((f) => [f.properties.section_id, f.properties]));
ok(propsById.sA && propsById.sA.name === "Alpha" && propsById.sA.color === "#f00",
   "feature carries safe render properties (name, color) for sA");
ok(propsById.sA.selected === false && propsById.sC.selected === false,
   "unselected sections marked selected=false");
ok(propsById.sB.selected === true, "only the selectedId section is marked selected=true");

// Changing selectedId keeps all three features (only the 'selected' flag moves).
const fcAll2 = cv.buildAllSectionsFC(secs3, "sC");
ok(fcAll2.features.length === 3, "changing selectedId does NOT drop other polygons");
const p2 = Object.fromEntries(fcAll2.features.map((f) => [f.properties.section_id, f.properties]));
ok(p2.sA.selected === false && p2.sB.selected === false && p2.sC.selected === true,
   "'selected' flag moves to the new selectedId; peers stay");

// selectedId = null / unknown => zero features are selected but all still present.
const fcNone = cv.buildAllSectionsFC(secs3, null);
ok(fcNone.features.length === 3 && fcNone.features.every((f) => f.properties.selected === false),
   "null selectedId => all features present, none selected");
const fcUnk = cv.buildAllSectionsFC(secs3, "does-not-exist");
ok(fcUnk.features.every((f) => f.properties.selected === false),
   "unknown selectedId => nothing selected but all features preserved");

// Sections without geometry are skipped; sections with geometry are kept.
const mixed = [
  { id: "s1", name: "has geom", geometry: g1 },
  { id: "s2", name: "no geom" },              // must be skipped
  { id: "s3", name: "null geom", geometry: null },  // must be skipped
  { id: "s4", name: "also has geom", geometry: g2 },
];
const fcMixed = cv.buildAllSectionsFC(mixed, "s1");
ok(fcMixed.features.length === 2, "sections without geometry are skipped");
const mixedIds = fcMixed.features.map((f) => f.properties.section_id);
ok(mixedIds.includes("s1") && mixedIds.includes("s4") && !mixedIds.includes("s2") && !mixedIds.includes("s3"),
   "only sections with geometry are included");

// Empty / null / undefined section inputs => empty FeatureCollection (never throws).
ok(cv.buildAllSectionsFC([], "any").features.length === 0, "empty sections => empty FC");
ok(cv.buildAllSectionsFC(null).features.length === 0, "null sections => empty FC");
ok(cv.buildAllSectionsFC(undefined).features.length === 0, "undefined sections => empty FC");

// Safe default rendering props when name/color are absent.
const bare = cv.buildAllSectionsFC([{ id: "sX", geometry: g1 }], "sX");
ok(bare.features[0].properties.section_id === "sX" && bare.features[0].properties.name === ""
   && bare.features[0].properties.color === null && bare.features[0].properties.selected === true,
   "missing name/color coerce to safe defaults");

// Geometry is DEEP-COPIED into the FC (mutation isolation): equal by value, NOT the same reference,
// so a consumer mutating a rendered feature can never bleed back into the source section.
const _fA = fcAll.features.find((f) => f.properties.section_id === "sA");
ok(JSON.stringify(_fA.geometry) === JSON.stringify(g1) && _fA.geometry !== g1,
   "section geometry deep-copied (equal by value, isolated reference)");


if (failures) { console.error(`\nCANVASS HELPERS: ${failures} failure(s)`); process.exit(1); }
console.log("\nCANVASS HELPERS: all passed");
