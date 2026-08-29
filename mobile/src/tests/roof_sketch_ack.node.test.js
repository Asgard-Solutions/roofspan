"use strict";
// B3B1 contracts: generation-safe acknowledgement + CAS rebase (pure production decision path).
const assert = require("assert");
const { applySketchAck, guardVersionFloor, reconcileDraftWrite } = require("../roofSketchAck");
const { createSketchSyncCoordinator } = require("../roofSketchSyncCoordinator");
const { makeSketchDraft } = require("../sketchCache");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };
const draftOf = (rev, str, gen, ver) => makeSketchDraft(rev, str, { document: { vertices: [{ id: "v" + gen, x: gen, y: 0 }] }, documentVersion: ver, editGeneration: gen });
const server = (ver) => ({ document_version: ver, document: { vertices: [] }, edit_mode: "connected_graph" });

(async () => {
// Case 1 — matched: retire only that exact draft generation + cache server
{
  const d = applySketchAck({ draft: draftOf("R", "S", 10, 5), ackGeneration: 10, serverValue: server(6) });
  assert.strictEqual(d.case, "matched"); assert.strictEqual(d.retireDraft, true);
  assert.deepStrictEqual(d.cacheServer, server(6)); assert.strictEqual(d.requeue, null);
  ok("matching acknowledgement retires only that exact draft generation + caches the Office response");
}

// Case 2 — Save(A)+Edit(B): A ack while B exists preserves B, advances 5 -> 6, keeps B pending
{
  const B = draftOf("R", "S", 11, 5); // B built at stale version 5
  const d = applySketchAck({ draft: B, ackGeneration: 10, serverValue: server(6) });
  assert.strictEqual(d.case, "superseded");
  assert.strictEqual(d.retireDraft, false, "B draft NOT cleared");
  assert.strictEqual(d.nextDraft.edit_generation, 11, "B generation preserved");
  assert.strictEqual(d.nextDraft.document.vertices[0].id, "v11", "B document preserved (not overwritten by A)");
  assert.strictEqual(d.nextDraft.document_version, 6, "B authoritative base advanced 5 -> 6");
  assert.strictEqual(d.requeue.expected_version, 6, "B queued expected_version advances to 6");
  ok("A acknowledgement while B exists preserves B's document + generation, advances B to v6, leaves B pending");
}

// A cannot resurrect/overwrite B in the queue: superseded writeback is a no-op by generation (existing
// supersession) — here we assert the decision never asks to retire or replace B.
{
  const d = applySketchAck({ draft: draftOf("R", "S", 11, 5), ackGeneration: 10, serverValue: server(6) });
  assert.ok(!d.retireDraft && d.nextDraft.edit_generation === 11); ok("A ack cannot overwrite or resurrect B");
}

// Reverse race — B staged after A ack must not regress v6 back to v5
{
  const co = createSketchSyncCoordinator({ queueMutation: async () => ({}) });
  co.noteServerVersion("R", "S", 6);
  let captured = null;
  const co2 = createSketchSyncCoordinator({ queueMutation: async (spec) => { captured = spec; return {}; } });
  co2.noteServerVersion("R", "S", 6);
  const r = await co2.stage({ revisionId: "R", structureId: "S", document: { vertices: [] }, documentVersion: 5, editMode: "connected_graph", editGeneration: 12, durable: true });
  assert.strictEqual(r.expectedVersion, 6, "staging floored to known server version");
  assert.strictEqual(captured.body.expected_version, 6); ok("reverse race: B staged with stale v5 after ack cannot regress below known v6");
  assert.strictEqual(guardVersionFloor(5, 6), 6); ok("guardVersionFloor never regresses a known CAS version");
}

// reconcileDraftWrite: monotonic generation + version floor
{
  const existing = draftOf("R", "S", 11, 6);
  const stale = reconcileDraftWrite(existing, draftOf("R", "S", 10, 5), 6);
  assert.strictEqual(stale.write, false); ok("a late older local write cannot clobber a newer generation");
  const newer = reconcileDraftWrite(existing, draftOf("R", "S", 12, 5), 6);
  assert.strictEqual(newer.write, true); assert.strictEqual(newer.draft.document_version, 6); ok("a newer local write persists but is floored to the known CAS version (never regresses)");
}

// after B succeeds at v7, B's draft retires if no newer local generation exists
{
  const d = applySketchAck({ draft: draftOf("R", "S", 11, 6), ackGeneration: 11, serverValue: server(7) });
  assert.strictEqual(d.retireDraft, true); assert.deepStrictEqual(d.cacheServer, server(7));
  ok("after B succeeds at v7 with no newer local work, B's draft retires");
}

// structure independence
{
  const house = applySketchAck({ draft: draftOf("R", "HOUSE", 10, 5), ackGeneration: 10, serverValue: server(6) });
  const garage = applySketchAck({ draft: draftOf("R", "GARAGE", 3, 2), ackGeneration: 2, serverValue: server(9) });
  assert.strictEqual(house.retireDraft, true);
  assert.strictEqual(garage.case, "superseded"); assert.strictEqual(garage.nextDraft.edit_generation, 3);
  ok("Main House and Garage acknowledgements remain independent");
}

// release example: A expected=5 -> B created -> A success=6 -> B expected 6 -> B success=7, no loss of B
{
  const B = draftOf("R", "S", 11, 5);
  const afterA = applySketchAck({ draft: B, ackGeneration: 10, serverValue: server(6) });
  assert.strictEqual(afterA.requeue.expected_version, 6);
  const afterB = applySketchAck({ draft: afterA.nextDraft, ackGeneration: 11, serverValue: server(7) });
  assert.strictEqual(afterB.retireDraft, true); ok("release example A5->B->A6->B6->B7 completes with zero loss of B");
}

console.log("\nFIELD SKETCH ACK / CAS REBASE (B3B1): all " + n + " assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
