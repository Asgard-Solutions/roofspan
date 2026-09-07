/*
 * RoofSpan Mobile — P0 regression: My Area map DATA FLOW invariants.
 *
 * Pure Node test (no device). Asserts the invariants that the fix depends on:
 *   1. Full property dataset is INDEPENDENT of canvass sections. Selecting a section
 *      does NOT mutate/replace the master property collection.
 *   2. Zero canvass sections => master property collection stays populated
 *      (the section overlay is empty, but the map is still usable).
 *   3. Cache-key contract: CACHE_MAP_PROPS is a SINGLE cache (NOT section-keyed);
 *      CACHE_SECTIONS / CACHE_MAP_CFG are their own independent keys. propsCacheKey(id)
 *      remains section-scoped for the LEGACY section overlay cache but must not be
 *      confused with the full-map cache.
 *   4. Failure isolation: one dataset failing (canvass endpoint OR /mobile/map/properties
 *      OR /map-config) does not clear the others.
 *
 * Run: node src/tests/map_data_flow.node.test.js
 */
const cv = require("../canvass");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

// ---------- Cache-key contract ----------
ok(cv.CACHE_MAP_PROPS === "map_props_full", "CACHE_MAP_PROPS is the single full-map cache key");
ok(cv.CACHE_SECTIONS === "canvass_sections", "CACHE_SECTIONS is a distinct cache key");
ok(cv.CACHE_MAP_CFG === "mapcfg", "CACHE_MAP_CFG is a distinct cache key");
ok(cv.CACHE_MAP_PROPS !== cv.CACHE_SECTIONS && cv.CACHE_MAP_PROPS !== cv.CACHE_MAP_CFG,
   "the three caches never collide");
// The full-map cache key must NOT be section-scoped: it stays stable across section changes.
ok(cv.CACHE_MAP_PROPS !== cv.propsCacheKey("s1"),
   "CACHE_MAP_PROPS is not section-keyed (per-section legacy cache remains distinct)");
ok(cv.propsCacheKey("s1") !== cv.propsCacheKey("s2"),
   "legacy per-section overlay cache is scoped per section");

// ---------- Small pure reducer mirroring MapScreen data invariants ----------
// State shape mirrors what MapScreen holds: {features, sections, selId, cfg, offlineNoCache}.
// Actions correspond to load-time and interaction events in MapScreen.js.
function reducer(state, action) {
  switch (action.type) {
    case "LOAD_RESULT": {
      // Independent datasets: each is applied only if it succeeded; failures fall back to cache
      // (represented here as the caller supplying `cached*` values). NEVER clear another dataset
      // because a peer failed.
      const next = { ...state };
      if (action.propsOk) next.features = action.features || [];
      else next.features = action.cachedFeatures != null ? action.cachedFeatures : state.features;
      if (action.secOk) next.sections = action.sections || [];
      else next.sections = action.cachedSections != null ? action.cachedSections : state.sections;
      if (action.cfgOk) next.cfg = action.cfg;
      else next.cfg = action.cachedCfg != null ? action.cachedCfg : state.cfg;
      // offlineNoCache: only when EVERYTHING failed AND nothing was cached.
      next.offlineNoCache = !action.propsOk && !action.secOk && !action.cfgOk &&
        (action.cachedFeatures == null || action.cachedFeatures.length === 0);
      // Default-select a section only if none is currently selected.
      if (!next.selId) next.selId = cv.pickDefaultSection(next.sections);
      return next;
    }
    case "SELECT_SECTION":
      // MUST NOT mutate features. Only changes the highlight/camera target.
      return { ...state, selId: action.id };
    default:
      return state;
  }
}
const INIT = { features: [], sections: [], selId: null, cfg: null, offlineNoCache: false };

// ---------- Invariant 1: full properties + one assigned section ----------
const feats3 = [
  { type: "Feature", geometry: { type: "Point", coordinates: [1, 1] }, properties: { id: "p1" } },
  { type: "Feature", geometry: { type: "Point", coordinates: [2, 2] }, properties: { id: "p2" } },
  { type: "Feature", geometry: { type: "Point", coordinates: [9, 9] }, properties: { id: "p3" } },
];
const secGeo = { type: "Polygon", coordinates: [[[0, 0], [0, 3], [3, 3], [3, 0], [0, 0]]] };
let s = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: true, features: feats3,
  secOk: true, sections: [{ id: "s1", geometry: secGeo }], cfgOk: true, cfg: { ok: 1 },
});
ok(s.features.length === 3, "full property dataset populated regardless of section geometry");
ok(s.sections.length === 1 && s.selId === "s1", "default section selected");
// Section overlay derives from the selected section, master dataset unchanged.
const overlay = cv.buildSectionPolygonFC(s.sections.find((x) => x.id === s.selId));
ok(overlay.features.length === 1, "section overlay built from selected section");
ok(s.features.length === 3, "props outside the section still in master collection");

// ---------- Invariant 2: multiple sections; selecting one does NOT mutate features ----------
let s2 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: true, features: feats3,
  secOk: true, sections: [{ id: "s1", geometry: secGeo }, { id: "s2", geometry: secGeo }],
  cfgOk: true, cfg: { ok: 1 },
});
const before = s2.features;
s2 = reducer(s2, { type: "SELECT_SECTION", id: "s2" });
ok(s2.selId === "s2", "SELECT_SECTION updates highlight");
ok(s2.features === before, "SELECT_SECTION does NOT mutate/replace master feature collection");
ok(s2.features.length === 3, "master feature count preserved after selection change");

// ---------- Invariant 3: zero canvass sections keeps full map ----------
const s3 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: true, features: feats3,
  secOk: true, sections: [], cfgOk: true, cfg: { ok: 1 },
});
ok(s3.features.length === 3, "zero sections user still has full property dataset");
ok(s3.sections.length === 0, "sections array is empty");
ok(s3.selId === null, "no default selection when zero sections");
ok(s3.cfg !== null, "map config preserved for basemap");
ok(s3.offlineNoCache === false, "zero sections must NOT trigger offline-no-cache blocker");

// ---------- Invariant 4: failure isolation ----------
// (a) canvass endpoint fails, props + cfg succeed => map remains usable.
const f1 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: true, features: feats3,
  secOk: false, cachedSections: [], cfgOk: true, cfg: { ok: 1 },
});
ok(f1.features.length === 3 && f1.cfg !== null,
   "canvass failure alone => properties + config still available");
ok(f1.offlineNoCache === false, "canvass failure alone => map is not blocked");

// (b) /mobile/map/properties fails but cache has data => cached props used, no blocker.
const f2 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: false, cachedFeatures: feats3,
  secOk: true, sections: [], cfgOk: true, cfg: { ok: 1 },
});
ok(f2.features.length === 3, "props endpoint failure falls back to CACHE_MAP_PROPS");
ok(f2.offlineNoCache === false, "cache hit means we do NOT show offline-no-cache blocker");

// (c) map-config fails but has a cached config => cached cfg used, props/sections untouched.
const f3 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: true, features: feats3,
  secOk: true, sections: [{ id: "s1", geometry: secGeo }],
  cfgOk: false, cachedCfg: { cached: true },
});
ok(f3.cfg && f3.cfg.cached === true, "map-config failure falls back to CACHE_MAP_CFG");
ok(f3.features.length === 3 && f3.sections.length === 1,
   "map-config failure does NOT discard properties/sections");

// (d) Total failure with cached props => still not the offline-no-cache blocker (map usable).
const f4 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: false, cachedFeatures: feats3,
  secOk: false, cachedSections: [], cfgOk: false, cachedCfg: { cached: true },
});
ok(f4.features.length === 3, "offline reopen restores last-good property map from CACHE_MAP_PROPS");
ok(f4.offlineNoCache === false, "cached props keep the map usable offline");

// (e) Total failure and NO cache anywhere => offline-no-cache blocker (only real block state).
const f5 = reducer(INIT, {
  type: "LOAD_RESULT", propsOk: false, cachedFeatures: [],
  secOk: false, cachedSections: [], cfgOk: false, cachedCfg: null,
});
ok(f5.offlineNoCache === true, "no data + no cache is the ONLY state that shows offline-no-cache");

if (failures) { console.error(`\nMAP DATA FLOW: ${failures} FAILURE(S)`); process.exit(1); }
console.log("\nMAP DATA FLOW: all passed");
process.exit(0);
