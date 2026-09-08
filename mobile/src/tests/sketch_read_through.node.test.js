"use strict";
/* RoofSpan Field — Roof-sketch GET READ-THROUGH contract (pure Node, dependency-injected).
 * Proves the REAL api/cache semantics (not hand-built envelopes): an authoritative HTTP 404 means
 * "no saved sketch yet" (never a load failure), a network/relay failure falls back to cache, and a 404
 * retires any obsolete cached sketch. The produced envelopes are then fed into the production viewer
 * resolver to prove the end-to-end behavior the P0 regression is about. */
const assert = require("assert");
const { readThroughSketch } = require("../sketchReadThrough");
const WIRE = require("../roofSketchFieldWiring");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// Mimic api.get(): HTTP 4xx throws an Error carrying e.response.status AND e.response.data (the parsed
// body, e.g. { detail: {...} }) — see mobile/src/api.js _throwOn4xx.
function httpError(status, detail) { const e = new Error("http_" + status); e.response = { status, data: { detail } }; return e; }
// A genuine network/relay failure throws WITHOUT an HTTP response.
function networkError() { return new Error("relay_unreachable"); }

const SKETCH = { structure_id: "s1", document_version: 4, edit_mode: "connected_graph", document: {
  edit_mode: "connected_graph",
  vertices: [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 }],
  edges: [{ id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" }, { id: "e3", v1: "v3", v2: "v4" }, { id: "e4", v1: "v4", v2: "v1" }],
  facets: [{ id: "f1", label: "F1", pitch_rise: 6, edges: ["e1", "e2", "e3", "e4"] }], penetrations: [],
} };

// A tiny in-memory cache to observe put/clear behaviour.
function makeStore(initial) {
  const map = new Map(Object.entries(initial || {}));
  return {
    map,
    getCache: async (k) => (map.has(k) ? map.get(k) : null),
    getCacheMeta: async (k) => (map.has(k) ? { updated_at: "2026-06-01T00:00:00Z" } : null),
    putCache: async (k, v) => { map.set(k, v); },
    clearCache: async (k) => { map.set(k, null); },
  };
}

(async () => {
  // ---- 1) Existing sketch (HTTP 200) ---------------------------------------------------------------
  {
    const st = makeStore();
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => ({ data: SKETCH }), ...st });
    assert.deepStrictEqual([env.stale, env.notFound, env.error], [false, false, null], "200 → fresh, not notFound, no error");
    assert.strictEqual(env.data, SKETCH, "200 → returns the sketch and caches it");
    assert.strictEqual(st.map.get("sk:s1"), SKETCH, "200 → sketch written to cache");
    const res = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(res.initial.source, "server", "200 → editor opens the Office sketch");
    ok("existing sketch: HTTP 200 → fresh envelope, cached, viewer opens the server sketch");
  }

  // ---- 2) THE REGRESSION: authoritative sketch_not_found 404 = 'no sketch yet' (NOT a load failure) ---
  {
    const st = makeStore({ "sk:s1": SKETCH });   // an obsolete cached sketch is present
    const detail = { code: "sketch_not_found", message: "No sketch for this structure yet" };
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw httpError(404, detail); }, ...st });
    assert.deepStrictEqual([env.data, env.stale, env.notFound, env.error], [null, false, true, null], "sketch_not_found 404 → data:null, stale:false, notFound:true, error:null");
    assert.strictEqual(st.map.get("sk:s1"), null, "sketch_not_found 404 → obsolete cached sketch is RETIRED (cannot resurrect)");
    // Editable revision → first-time creation must be allowed, NOT an error screen.
    const editable = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(editable.phase, "ready", "editable + sketch_not_found → ready (Sketch Roof works)");
    assert.strictEqual(editable.initial.source, "new", "editable + sketch_not_found → a new editable sketch is created");
    assert.strictEqual(editable.diagnostics.sketchLoadFailed, false, "editable + sketch_not_found → NOT flagged as a load failure");
    // Locked revision → honest empty state, never a fabricated blank sketch.
    const locked = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: true });
    assert.strictEqual(locked.phase, "empty_readonly", "locked + sketch_not_found → empty_readonly (no sketch message)");
    assert.strictEqual(locked.initial, undefined, "locked + sketch_not_found → no fabricated sketch");
    ok("REGRESSION FIXED: sketch_not_found 404 → first-time Sketch Roof works (editable) / honest empty (locked), cache retired");
  }

  // ---- 2b) LEGACY exact-string 404 (backward compatibility during rollout) --------------------------
  {
    const st = makeStore({ "sk:s1": SKETCH });
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw httpError(404, "No sketch for this structure yet"); }, ...st });
    assert.strictEqual(env.notFound, true, "legacy exact-string 404 → still recognized as no-sketch");
    const editable = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(editable.initial.source, "new", "legacy 404 → editable revision still creates a first sketch");
    ok("legacy exact-string 404 → same no-sketch behavior (backward compatible)");
  }

  // ---- 2c) MISSING/STALE revision 404 must NOT be no-sketch → reload/error, never a blank sketch ----
  {
    const st = makeStore({ "sk:s1": SKETCH });   // stale cache must NOT be served for a dead revision
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw httpError(404, "Measurement revision not found"); }, ...st });
    assert.deepStrictEqual([env.data, env.notFound], [null, false], "missing-revision 404 → data:null, notFound:false (not a no-sketch)");
    assert.ok(env.error, "missing-revision 404 preserves the error");
    assert.strictEqual(st.map.get("sk:s1"), SKETCH, "missing-revision 404 → cache is NOT retired here (only sketch_not_found retires)");
    const editable = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(editable.phase, "error", "missing-revision 404 → reload/error state, NEVER a new blank sketch");
    ok("missing/stale revision 404 → reload/error (does not open a blank or cached sketch)");
  }

  // ---- 2d) Generic/unknown 404 must NOT become notFound ---------------------------------------------
  {
    const st = makeStore();
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw httpError(404, "Some other thing"); }, ...st });
    assert.strictEqual(env.notFound, false, "generic 404 → NOT classified as no-sketch");
    const res = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(res.phase, "error", "generic 404 → reload/error, not a fabricated sketch");
    ok("generic/unknown 404 → NOT no-sketch, surfaces as error");
  }

  // ---- 2e) 403 stays an authorization error (no cached sketch served) -------------------------------
  {
    const st = makeStore({ "sk:s1": SKETCH });
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw httpError(403, "You are not authorized for this measurement."); }, ...st });
    assert.deepStrictEqual([env.data, env.notFound], [null, false], "403 → data:null, notFound:false (never serves cached data)");
    assert.ok(env.error, "403 preserves the authorization error");
    ok("403 → authorization error, never opens a cached sketch");
  }

  // ---- 3) Network/relay failure with NO cache → retryable load error ------------------------------
  {
    const st = makeStore();
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw networkError(); }, ...st });
    assert.deepStrictEqual([env.data, env.stale, env.notFound], [null, true, false], "network fail, no cache → data:null, stale:true, notFound:false");
    assert.ok(env.error, "network fail preserves the error");
    const res = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: false });
    assert.strictEqual(res.phase, "error", "network fail + no cache → retryable error (never a blank sketch)");
    ok("network/relay failure + no cache → retryable error");
  }

  // ---- 4) Network/relay failure WITH a cached sketch → open cached geometry, flag stale ------------
  {
    const st = makeStore({ "sk:s1": SKETCH });
    const env = await readThroughSketch({ name: "sk:s1", fetcher: async () => { throw networkError(); }, ...st });
    assert.deepStrictEqual([env.stale, env.notFound], [true, false], "network fail + cache → stale:true, notFound:false");
    assert.strictEqual(env.data, SKETCH, "network fail + cache → returns the cached sketch");
    const res = WIRE.resolveFieldSketchViewerOpen({ draft: null, sketchResult: env, mutation: null, mutationError: null, structureId: "s1", readOnly: true });
    assert.strictEqual(res.phase, "ready", "network fail + cache → viewer opens from cache");
    assert.strictEqual(res.initial.source, "server", "network fail + cache → cached Office copy is authoritative");
    assert.strictEqual(res.statusMeta.stale, true, "network fail + cache → stale/offline surfaced (drives 'Read only · Offline/cached')");
    ok("network/relay failure + cached sketch → cached geometry opens, offline/cached indicated");
  }

  console.log("\nSKETCH READ-THROUGH CONTRACT: all " + n + " assertions passed");
})().catch((e) => { console.error("  \u2717 FAIL:", e && e.message); process.exit(1); });
