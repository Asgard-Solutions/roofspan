"use strict";
/* RoofSpan Field — P0 LOCKED ROOF SKETCH VIEWER open resolution (pure Node).
 * The confirmed P0: a locked measurement revision's Roof Sketch was stuck on "Locked" and never rendered
 * because the OPTIONAL queue lookup (currentSketchMutation) could throw during open and strand the viewer,
 * and "Locked" was (mis)used as the loading label. These contracts pin the real production decision path
 * used by RoofSketch.js so a locked sketch OPENS read-only, optional deps are fault-isolated, and real
 * load failures are surfaced honestly (never a fabricated blank sketch). */
const assert = require("assert");
const WIRE = require("../roofSketchFieldWiring");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// A real roof sketch document with drawable geometry.
const geomDoc = {
  edit_mode: "connected_graph",
  vertices: [{ id: "v1", x: 0, y: 0 }, { id: "v2", x: 10, y: 0 }, { id: "v3", x: 10, y: 8 }, { id: "v4", x: 0, y: 8 }],
  edges: [{ id: "e1", v1: "v1", v2: "v2" }, { id: "e2", v1: "v2", v2: "v3" }, { id: "e3", v1: "v3", v2: "v4" }, { id: "e4", v1: "v4", v2: "v1" }],
  facets: [{ id: "f1", label: "F1", pitch_rise: 6, edges: ["e1", "e2", "e3", "e4"] }],
  penetrations: [],
};
const serverSketch = (document, document_version = 3) => ({ document, document_version, edit_mode: "connected_graph" });
const draftOf = (document, document_version = 2) => ({ document, document_version, edit_generation: 4, base_server_document: document, edit_mode: "connected_graph" });

function geometryPresent(initial) {
  const d = initial && initial.document;
  return !!(d && (d.vertices || []).length >= 3 && (d.edges || []).length >= 3 && (d.facets || []).length >= 1);
}

// ---- 1) THE P0: existing locked (read-only) sketch + currentSketchMutation() throws ----------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null,
    sketchResult: { data: serverSketch(geomDoc, 3), stale: false },
    mutation: undefined,
    mutationError: new Error("SQLite read failed"),  // OPTIONAL queue lookup threw during open
    structureId: "s1",
    readOnly: true,
  });
  assert.strictEqual(res.phase, "ready", "locked sketch still resolves to a usable viewer despite queue-lookup failure");
  assert.ok(res.initial, "a usable editor/viewer model was created");
  assert.strictEqual(res.initial.source, "server", "opens the authoritative Office sketch");
  assert.ok(geometryPresent(res.initial), "existing geometry is present (renders the full sketch, not blank)");
  assert.strictEqual(res.hasActiveMutation, false, "queue-lookup failure defaults to NO active mutation (never staged)");
  assert.strictEqual(res.diagnostics.mutationLookupFailed, true, "the queue-lookup failure is recorded (never swallowed)");
  assert.strictEqual(res.diagnostics.sketchLoadFailed, false, "the sketch itself loaded fine");
  ok("P0: existing locked sketch + queue-lookup throw → viewer opens read-only with full geometry, no mutation");
}

// ---- 2) Locked cached sketch while OFFLINE (read-through fell back to the cached copy) --------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null,
    sketchResult: { data: serverSketch(geomDoc, 3), stale: true, cachedAt: "2026-06-01T00:00:00Z", error: new Error("offline") },
    mutation: null, mutationError: null, structureId: "s1", readOnly: true,
  });
  assert.strictEqual(res.phase, "ready", "locked cached sketch opens offline");
  assert.strictEqual(res.initial.source, "server", "the cached Office copy is authoritative offline");
  assert.ok(geometryPresent(res.initial), "cached geometry is present offline");
  assert.strictEqual(res.statusMeta.stale, true, "status meta reports the offline/cached copy honestly");
  ok("locked cached sketch while offline → opens read-only from cache (stale flagged)");
}

// ---- 3) Locked + NO saved sketch (no draft, no server/cached copy) ---------------------------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null,
    sketchResult: { data: null, stale: false },   // server legitimately has no sketch for this structure
    mutation: null, mutationError: null, structureId: "s1", readOnly: true,
  });
  assert.strictEqual(res.phase, "empty_readonly", "locked + no sketch → explicit empty state");
  assert.strictEqual(res.initial, undefined, "no fabricated blank/new sketch is created for a locked revision");
  ok("locked + no saved sketch → honest 'no sketch' state, never a blank editable sketch");
}

// ---- 4) Real sketch load failure with NO cache (and no local draft) --------------------------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null,
    sketchResult: { data: null, stale: true, error: new Error("network") },  // hard failure, nothing cached
    mutation: null, mutationError: null, structureId: "s1", readOnly: true,
  });
  assert.strictEqual(res.phase, "error", "unresolvable sketch load with no cache → retryable error");
  assert.strictEqual(res.reason, "sketch_load_failed", "the failure reason is explicit");
  assert.strictEqual(res.initial, undefined, "never marked ready with incomplete data");
  assert.strictEqual(res.diagnostics.sketchLoadFailed, true, "the load failure is recorded, not hidden");
  ok("real sketch-load failure with no cache → explicit retryable error (never ready-with-nothing)");
}
// ...same for an EDITABLE revision (an offline brand-new open cannot fabricate a sketch either).
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null, sketchResult: { data: null, stale: true, error: new Error("network") },
    mutation: null, mutationError: null, structureId: "s1", readOnly: false,
  });
  assert.strictEqual(res.phase, "error", "editable open also surfaces a hard load failure with no cache");
  ok("editable revision: hard load failure with no cache → retryable error, not a blank sketch");
}

// ---- 5) Editable sketch still works NORMALLY (existing server sketch, no failures) -----------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null, sketchResult: { data: serverSketch(geomDoc, 3), stale: false },
    mutation: null, mutationError: null, structureId: "s1", readOnly: false,
  });
  assert.strictEqual(res.phase, "ready", "editable existing sketch opens normally");
  assert.strictEqual(res.initial.source, "server", "adopts the Office sketch for editing");
  assert.ok(geometryPresent(res.initial), "geometry present for editing");
  ok("editable existing sketch → opens normally for editing");
}
// Editable brand-new sketch (server has none, no error) is a LEGITIMATE new-document open.
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null, sketchResult: { data: null, stale: false },
    mutation: null, mutationError: null, structureId: "s1", readOnly: false,
  });
  assert.strictEqual(res.phase, "ready", "editable + no sketch → start a new sketch");
  assert.strictEqual(res.initial.source, "new", "a fresh new document is created ONLY for an editable revision");
  ok("editable + no sketch → new sketch document (never for a locked revision)");
}

// ---- 6) Local draft is preserved even when the sketch load fails (offline usability) ---------------
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: draftOf(geomDoc, 2),
    sketchResult: { data: null, stale: true, error: new Error("network") },  // Office unreachable
    mutation: { state: "pending" }, mutationError: null, structureId: "s1", readOnly: false,
  });
  assert.strictEqual(res.phase, "ready", "a local draft opens even when the Office copy cannot be fetched");
  assert.strictEqual(res.initial.source, "local_draft", "unsynced local work stays authoritative");
  assert.strictEqual(res.hasActiveMutation, true, "the active pending mutation is honored");
  ok("local draft + sketch load failure → local work preserved and opened (never lost)");
}

// ---- 7) hasActiveMutation is fault-isolated: a lookup error can NEVER read as an active mutation ----
{
  const res = WIRE.resolveFieldSketchViewerOpen({
    draft: null, sketchResult: { data: serverSketch(geomDoc, 3), stale: false },
    mutation: { state: "pending" }, mutationError: new Error("boom"), structureId: "s1", readOnly: true,
  });
  assert.strictEqual(res.hasActiveMutation, false, "a queue-lookup error forces hasActiveMutation=false");
  assert.strictEqual(res.phase, "ready", "and the viewer still opens");
  ok("queue-lookup error → hasActiveMutation defaults false (safe), viewer still opens");
}

console.log("\nP0 LOCKED ROOF SKETCH VIEWER: all " + n + " assertions passed");
