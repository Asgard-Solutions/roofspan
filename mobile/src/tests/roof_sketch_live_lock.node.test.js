"use strict";
// B3D contracts: LIVE measurement-revision locking + app-lifecycle durability for the OPEN Field Roof
// Sketch editor. Exercises the SAME pure paths production uses (queue.processMutation/processQueue,
// WIRE.* helpers, the controller + coordinator staging via WIRE.stageFromController). NO React/RN.
//
// Invariants proven here:
//   • the locked classification is SCOPED to measurement_sketch_update and keyed on the ACTUAL backend
//     response shape (a sketch conflict always carries detail.server; the immutable-revision refusal
//     does not) — never a broad global "locked" substring rule that could hit unrelated mutations,
//   • a locked mutation is DURABLE + terminal: it is never auto-retried and the salesperson's unsynced
//     document + local edit generation are preserved verbatim,
//   • a pre-existing conflict is never auto-resent or auto-resolved (conflict-then-lock protection),
//   • editing is blocked the moment a lock is known,
//   • background flush stages the LATEST COMMITTED generation, serialized after durable local persist,
//   • structures remain isolated.
const assert = require("assert");
const queue = require("../queue");
const WIRE = require("../roofSketchFieldWiring");
const { createFieldEditor } = require("../roofSketchFieldController");
const { createSketchSyncCoordinator } = require("../roofSketchSyncCoordinator");
const RS = require("@roofspan/roof-sketch-core");
const { sketchUpdateMutationId } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const LOCK_DETAIL = "This measurement revision is locked. Create a new revision to edit its sketch.";
const geom = (x) => ({ vertices: [{ id: "v1", x, y: 0 }], edges: [], facets: [] });
function sketchMut(rev, str, gen, doc) {
  return queue.makeMutation({
    kind: "measurement_sketch_update", method: "put",
    path: `/mobile/measurements/${rev}/sketches/${str}`,
    clientId: sketchUpdateMutationId(rev, str),
    body: { schema_version: 1, edit_mode: "connected_graph", document: doc, expected_version: 4 },
    localEditGeneration: gen,
  });
}

(async () => {
  // ---- 1. immutable/locked revision 409 (STRING detail, no `server`) -> durable LOCKED, work preserved ----
  {
    const doc = geom(7);
    const m = sketchMut("R", "HOUSE", 9, doc);
    const res = { status: 409, data: { detail: LOCK_DETAIL } };
    const out = await queue.processMutation(m, async () => res);
    assert.strictEqual(out.state, "locked", "sketch lock 409 -> LOCKED state");
    assert.strictEqual(out.errorCode, "revision_locked");
    assert.ok(/locked/i.test(out.error));
    assert.strictEqual(out.serverValue, null, "no conflict serverValue on a lock");
    assert.deepStrictEqual(out.body.document, doc, "unsynced local geometry preserved verbatim");
    assert.strictEqual(out.local_edit_generation, 9, "local edit generation preserved");
    ok("sketch immutable-revision 409 (string detail) -> durable LOCKED; local document + generation preserved");
  }

  // ---- 2. genuine sketch version conflict (OBJECT detail WITH `server`) -> CONFLICT (unchanged) ----
  {
    const m = sketchMut("R", "HOUSE", 3, geom(1));
    const server = { document_version: 8, document: geom(2), edit_mode: "connected_graph" };
    const out = await queue.processMutation(m, async () => ({ status: 409, data: { detail: { message: "changed", server } } }));
    assert.strictEqual(out.state, "conflict", "sketch conflict 409 (with server) -> CONFLICT");
    assert.deepStrictEqual(out.serverValue, server, "authoritative Office sketch retained for review");
    assert.notStrictEqual(out.state, "locked");
    ok("genuine sketch version conflict (detail.server present) stays CONFLICT with authoritative server data");
  }

  // ---- 3. SCOPE GUARD: a NON-sketch 409 whose message contains 'locked' is NEVER classified locked ----
  {
    const pm = queue.makeMutation({ kind: "property_patch", method: "patch", path: "/mobile/properties/p1", body: { x: 1 } });
    const out = await queue.processMutation(pm, async () => ({ status: 409, data: { detail: "record locked by another user" } }));
    assert.strictEqual(out.state, "conflict", "unrelated 409 is NOT hijacked into locked");
    assert.notStrictEqual(out.state, "locked");
    ok("scope guard: a non-sketch 409 containing the word 'locked' remains CONFLICT (never locked)");
  }

  // ---- 4. SCOPE GUARD: a non-sketch 409 without server stays conflict (existing behavior) ----
  {
    const vm = queue.makeMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { outcome: "no_answer" } });
    const out = await queue.processMutation(vm, async () => ({ status: 409, data: { detail: { message: "conflict" } } }));
    assert.strictEqual(out.state, "conflict");
    ok("scope guard: non-sketch 409 classification unchanged (conflict)");
  }

  // ---- 5. a LOCKED mutation is NEVER auto-retried by processQueue (no endless retry) ----
  {
    const locked = { ...sketchMut("R", "HOUSE", 9, geom(7)), state: "locked", errorCode: "revision_locked" };
    let sends = 0;
    const out = await queue.processQueue([locked], async () => { sends++; return { status: 200 }; });
    assert.strictEqual(sends, 0, "send() never invoked for a locked row");
    assert.strictEqual(out[0].state, "locked", "row left untouched (still locked, still holding the work)");
    assert.deepStrictEqual(out[0].body.document, geom(7));
    ok("a LOCKED sketch mutation is never resent by processQueue (terminal, no endless retry)");
  }

  // ---- 6. CONFLICT-THEN-LOCK: a pre-existing conflict row is never auto-resent or auto-resolved ----
  {
    const conflict = { ...sketchMut("R", "HOUSE", 5, geom(3)), state: "conflict", serverValue: { document_version: 8, document: geom(2) } };
    let sends = 0;
    const out = await queue.processQueue([conflict], async () => { sends++; return { status: 200 }; });
    assert.strictEqual(sends, 0, "a conflict row is not auto-resent");
    assert.strictEqual(out[0].state, "conflict", "conflict preserved (not auto-resolved)");
    assert.deepStrictEqual(out[0].body.document, geom(3), "local draft/geometry preserved");
    assert.ok(out[0].serverValue, "conflict review information preserved");
    ok("conflict-then-lock: a pre-existing conflict is preserved — never auto-resent, never auto-resolved");
  }
  // and if the rep re-queues (keep-local -> pending) and the revision is now locked, the resend is LOCKED
  {
    const requeued = sketchMut("R", "HOUSE", 5, geom(3));   // pending again
    const out = await queue.processMutation(requeued, async () => ({ status: 409, data: { detail: LOCK_DETAIL } }));
    assert.strictEqual(out.state, "locked");
    assert.deepStrictEqual(out.body.document, geom(3), "kept-local geometry still preserved after hitting the lock");
    ok("keep-local re-send against a now-locked revision -> LOCKED with the local work preserved");
  }

  // ---- 7. live status label: locked -> 'Measurement revision locked' ----
  {
    const s = WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: { state: "locked" }, running: false, currentGeneration: 2, acknowledgedGeneration: 0 });
    assert.strictEqual(s, "Measurement revision locked");
    // device-durability still takes precedence when the local write itself failed
    assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Could not save on device", mutation: { state: "locked" }, running: false }), "Could not save on device");
    ok("locked mutation -> 'Measurement revision locked' (device-durability failures still reported first)");
  }

  // ---- 8. editing lock predicate blocks on locked (and on conflict / readOnly) ----
  {
    assert.strictEqual(WIRE.editingLocked({ locked: true }), true);
    assert.strictEqual(WIRE.editingLocked({ conflict: {} }), true);
    assert.strictEqual(WIRE.editingLocked({ readOnly: true }), true);
    assert.strictEqual(WIRE.editingLocked({ locked: false, conflict: null, readOnly: false }), false);
    assert.strictEqual(WIRE.deriveSketchLocked({ state: "locked" }), true);
    assert.strictEqual(WIRE.deriveSketchLocked({ state: "pending" }), false);
    assert.strictEqual(WIRE.deriveSketchLocked(null), false);
    ok("editingLocked blocks every edit path when locked; deriveSketchLocked reflects the durable row");
  }

  // ---- 9. live lock detected WHILE editing: refresh surfaces locked WITHOUT touching newer local work ----
  {
    const initial = { document: geom(1), editMode: "connected_graph", documentVersion: 4, editGeneration: 1, baseServerDocument: geom(0), source: "server" };
    const ed = createFieldEditor({ revisionId: "R", structureId: "HOUSE", initial, persist: async () => {} });
    ed.commit(geom(5));                       // local edit A -> gen 2 (newer than the server)
    const docA = ed.document, genA = ed.editGeneration;
    const state = { seq: 0, acked: 0, localSave: "Saved on device" };
    let shown = null; const setStatus = (s) => { shown = s; };
    const seq = WIRE.nextRefreshSeq(state);
    const lockedRow = { client_id: sketchUpdateMutationId("R", "HOUSE"), kind: "measurement_sketch_update", state: "locked", local_edit_generation: 2 };
    const draft = { document_version: 4, base_server_document: geom(0), document: docA };
    const r = WIRE.applySketchRefresh({ seq, state, editor: ed, mutation: lockedRow, draft, running: false, setStatus });
    assert.strictEqual(r.applied, true);
    assert.strictEqual(shown, "Measurement revision locked", "locked status surfaced");
    assert.strictEqual(ed.document, docA, "newer local geometry NOT replaced by stale server/cache");
    assert.strictEqual(ed.editGeneration, genA, "edit generation unchanged");
    assert.strictEqual(WIRE.deriveSketchLocked(lockedRow), true, "screen would block editing");
    ok("live lock during editing surfaces 'locked' + blocks, and never overwrites newer local work");
  }

  // ---- 10. structure isolation: a lock on HOUSE does not change GARAGE's own status ----
  {
    const all = [
      { client_id: sketchUpdateMutationId("R", "HOUSE"), state: "locked" },
      { client_id: sketchUpdateMutationId("R", "GARAGE"), state: "pending", local_edit_generation: 4 },
    ];
    const pick = (str) => all.find((x) => x.client_id === sketchUpdateMutationId("R", str)) || null;
    assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: pick("HOUSE"), running: false, currentGeneration: 2, acknowledgedGeneration: 0 }), "Measurement revision locked");
    assert.strictEqual(WIRE.fieldSketchSyncStatus({ localSave: "Saved on device", mutation: pick("GARAGE"), running: false, currentGeneration: 4, acknowledgedGeneration: 0 }), "Waiting to sync");
    ok("structure isolation: HOUSE locked does not affect GARAGE's pending status");
  }

  // ---- 11. BACKGROUND ORDERING: latest committed gen -> durable local persist -> durable queue stage ----
  {
    const order = [];
    // Async persist that records its ordering; stageFromController must await the serialized persist
    // chain (durable local persistence) BEFORE staging into the durable queue.
    const persist = async (draft, gen) => { order.push("persist:" + gen); await Promise.resolve(); order.push("persisted:" + gen); };
    const initial = { document: geom(1), editMode: "connected_graph", documentVersion: 4, editGeneration: 1, source: "server", baseServerDocument: geom(0) };
    const ed = createFieldEditor({ revisionId: "R", structureId: "HOUSE", initial, persist });
    ed.commit(geom(2));   // gen 2
    ed.commit(geom(3));   // gen 3 (latest committed)
    const q = []; const coordinator = createSketchSyncCoordinator({ queueMutation: async (spec) => { order.push("stage"); q.push(spec); return queue.makeMutation({ ...spec }); } });
    const r = await WIRE.stageFromController(ed, coordinator, { revisionId: "R", structureId: "HOUSE" });
    assert.ok(r.staged, "staged after persistence drained");
    assert.ok(order.indexOf("stage") > order.indexOf("persisted:3"), "stage happens AFTER the latest committed gen durably persists");
    assert.strictEqual(q[0].body.document.vertices[0].x, 3, "the LATEST COMMITTED generation (gen 3) is staged");
    assert.strictEqual(q[0].body.expected_version, 4, "CAS expected_version from the authoritative documentVersion");
    ok("background flush order: committed gen -> durable local persist -> durable queue stage (latest wins)");
  }

  // ---- 12. background flush of a NON-durable generation does NOT stage (persist must land first) ----
  {
    let fail = true;
    const ed = createFieldEditor({ revisionId: "R", structureId: "S1", initial: { document: geom(1), editMode: "connected_graph", editGeneration: 1, documentVersion: 2, source: "server", baseServerDocument: geom(0) }, persist: async (d, g) => { if (fail && g >= 2) throw new Error("disk busy"); } });
    ed.commit(geom(9));   // gen 2 fails to persist
    const q = []; const coordinator = createSketchSyncCoordinator({ queueMutation: async (spec) => { q.push(spec); return queue.makeMutation({ ...spec }); } });
    const r = await WIRE.stageFromController(ed, coordinator, { revisionId: "R", structureId: "S1" });
    assert.ok(!r.staged && r.reason === "not_durable", "non-durable generation is not staged on background");
    assert.strictEqual(q.length, 0, "nothing queued while local persistence has not landed");
    fail = false; await ed.retry();
    const r2 = await WIRE.stageFromController(ed, coordinator, { revisionId: "R", structureId: "S1" });
    assert.ok(r2.staged, "once durable, it stages");
    ok("background flush never stages a generation that has not durably persisted locally");
  }

  console.log("\nFIELD ROOF SKETCH LIVE LOCK + LIFECYCLE (B3D): all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
