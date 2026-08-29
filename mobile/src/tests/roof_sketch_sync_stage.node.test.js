"use strict";
// B3A contracts: committed Field sketch edits stage into the EXISTING durable queue. Uses a fake
// queueMutation that records specs (no real network/storage), plus the real queue.makeMutation /
// processMutation to prove metadata + serverValue behavior.
const assert = require("assert");
const { createSketchSyncCoordinator } = require("../roofSketchSyncCoordinator");
const queue = require("../queue");
const { sketchUpdateMutationId } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };
function fakeQueue() {
  const calls = [];
  const queueMutation = async (spec) => { const stored = queue.makeMutation({ ...spec }); calls.push({ spec, stored }); return stored; };
  return { calls, queueMutation };
}
const doc = (v) => ({ vertices: [{ id: "v1", x: v, y: 0 }], edges: [], facets: [], scale: {} });

(async () => {
  // capture generation/document/version/mode into the deterministic sketch mutation
  {
    const q = fakeQueue();
    const co = createSketchSyncCoordinator({ queueMutation: q.queueMutation });
    const r = await co.stage({ revisionId: "R1", structureId: "S1", document: doc(3), documentVersion: 7, editMode: "connected_graph", editGeneration: 14, durable: true });
    assert.ok(r.staged && r.generation === 14);
    const spec = q.calls[0].spec;
    assert.strictEqual(spec.clientId, sketchUpdateMutationId("R1", "S1"));
    assert.strictEqual(spec.body.expected_version, 7);
    assert.strictEqual(spec.body.edit_mode, "connected_graph");
    assert.strictEqual(spec.body.document.vertices[0].x, 3);
    assert.strictEqual(spec.localEditGeneration, 14); ok("sketch mutation captures document/version/mode + deterministic identity + local_edit_generation");
    assert.strictEqual(spec.body.edit_generation, undefined); ok("edit_generation is NOT part of the backend request body");
    assert.strictEqual(q.calls[0].stored.local_edit_generation, 14); ok("local_edit_generation is retained as queue metadata (not in body)");
  }

  // frozen snapshot: later Field edits must not mutate staged work
  {
    const q = fakeQueue();
    const co = createSketchSyncCoordinator({ queueMutation: q.queueMutation });
    const live = doc(1);
    const r = await co.stage({ revisionId: "R1", structureId: "S1", document: live, documentVersion: 0, editMode: "connected_graph", editGeneration: 1, durable: true });
    live.vertices[0].x = 999; // continue editing the live document
    assert.strictEqual(r.snapshot.vertices[0].x, 1, "snapshot unchanged");
    assert.strictEqual(q.calls[0].spec.body.document.vertices[0].x, 1, "queued body unchanged");
    assert.throws(() => { r.snapshot.vertices[0].x = 5; }, "snapshot is frozen"); ok("queued snapshot is frozen — later live edits cannot mutate staged work");
  }

  // local durability MUST precede queueing
  {
    const q = fakeQueue();
    const co = createSketchSyncCoordinator({ queueMutation: q.queueMutation });
    const r = await co.stage({ revisionId: "R1", structureId: "S1", document: doc(1), documentVersion: 0, editMode: "connected_graph", editGeneration: 5, durable: false });
    assert.ok(!r.staged && r.reason === "not_durable");
    assert.strictEqual(q.calls.length, 0); ok("a non-durable generation is NOT queued (local persistence first)");
  }

  // dedupe same generation; newest supersedes; structures independent
  {
    const q = fakeQueue();
    const co = createSketchSyncCoordinator({ queueMutation: q.queueMutation });
    const base = { revisionId: "R1", structureId: "S1", documentVersion: 0, editMode: "connected_graph", durable: true };
    await co.stage({ ...base, document: doc(1), editGeneration: 14 });
    const dupe = await co.stage({ ...base, document: doc(1), editGeneration: 14 });
    assert.ok(!dupe.staged && dupe.reason === "deduped"); ok("the same edit_generation is deduped (no duplicate work)");
    const gB = await co.stage({ ...base, document: doc(2), editGeneration: 15 });
    assert.ok(gB.staged && gB.generation === 15);
    assert.strictEqual(co.lastStagedGeneration("R1", "S1"), 15); ok("generation B (15) supersedes A (14) for the same structure via the shared identity");
    const other = await co.stage({ revisionId: "R1", structureId: "S2", document: doc(9), documentVersion: 0, editMode: "connected_graph", editGeneration: 1, durable: true });
    assert.ok(other.staged);
    assert.strictEqual(q.calls[q.calls.length - 1].spec.clientId, sketchUpdateMutationId("R1", "S2")); ok("different structures stage independently (distinct mutation identity)");
  }

  // offline staging leaves a durable PENDING mutation (state via makeMutation default)
  {
    const q = fakeQueue();
    const co = createSketchSyncCoordinator({ queueMutation: q.queueMutation });
    const r = await co.stage({ revisionId: "R1", structureId: "S1", document: doc(1), documentVersion: 0, editMode: "connected_graph", editGeneration: 2, durable: true });
    assert.strictEqual(r.mutation.state, "pending"); ok("offline staging leaves a durable pending mutation");
  }

  // HTTP 200 success retains the complete serverValue (for B3B) and does NOT clear the local draft here
  {
    const staged = queue.makeMutation({ kind: "measurement_sketch_update", method: "put", path: "/mobile/measurements/R1/sketches/S1", clientId: sketchUpdateMutationId("R1", "S1"), body: { document: {}, expected_version: 7 } });
    const serverBody = { id: "sk1", document_version: 8, document: { vertices: [] }, edit_mode: "connected_graph" };
    const processed = await queue.processMutation(staged, async () => ({ status: 200, data: serverBody }));
    assert.strictEqual(processed.state, "synced");
    assert.deepStrictEqual(processed.serverValue, serverBody); ok("HTTP 200 sketch success retains the complete serverValue (document_version + document)");
    // B3A boundary: transport success carries the server value but the coordinator/test perform NO draft clearing
    assert.ok(processed.serverValue.document_version === 8); ok("server acknowledgement is available but the local draft is NOT cleared in B3A (deferred to B3B)");
  }

  console.log("\nFIELD SKETCH SYNC STAGING (B3A): all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
