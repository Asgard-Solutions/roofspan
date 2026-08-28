"use strict";
const assert = require("assert");
const { makeMutation } = require("../queue");
const {
  sketchDetailKey, sketchDraftKey, sketchUpdateMutationId, sketchPath, makeSketchDraft, mergeSketchDraft,
} = require("../sketchCache");

let n = 0;
const ok = (m) => { n++; console.log("  \u2713 " + m); };

// deterministic keys
assert.strictEqual(sketchDetailKey("R1", "S1"), "sketch:R1:S1"); ok("detail key");
assert.strictEqual(sketchDraftKey("R1", "S1"), "sketch-draft:R1:S1"); ok("draft key");
assert.strictEqual(sketchUpdateMutationId("R1", "S1"), "measurement-sketch-update:R1:S1"); ok("mutation id");

// repeated offline edits of ONE structure reuse the same mutation id (coalesce)
const path = sketchPath("R1", "S1");
const m1 = makeMutation({ kind: "measurement_sketch_update", method: "put", path, body: { document_version: 3 } });
const m2 = makeMutation({ kind: "measurement_sketch_update", method: "put", path, body: { document_version: 4 } });
assert.strictEqual(m1.client_id, m2.client_id); ok("repeated edits to same structure coalesce to one mutation id");
assert.strictEqual(m1.client_id, "measurement-sketch-update:R1:S1"); ok("mutation id derived from revision+structure");

// two different structures -> different ids
const mOther = makeMutation({ kind: "measurement_sketch_update", method: "put", path: sketchPath("R1", "S2"), body: {} });
assert.notStrictEqual(m1.client_id, mOther.client_id); ok("different structure -> different mutation id");
// different revision -> different id
const mRev = makeMutation({ kind: "measurement_sketch_update", method: "put", path: sketchPath("R2", "S1"), body: {} });
assert.notStrictEqual(m1.client_id, mRev.client_id); ok("different revision -> different mutation id");

// existing measurement + photo identities must be unchanged
const meas = makeMutation({ kind: "measurement_update", method: "put", path: "/mobile/measurements/REVX", body: {} });
assert.strictEqual(meas.client_id, "measurement-update:REVX"); ok("existing measurement_update identity unchanged");
const photo = makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: {}, photo: { uri: "x" } });
assert.ok(photo.client_id && photo.client_id !== m1.client_id); ok("photo mutation identity independent");

// draft round-trip preserves local doc, version token, and base server doc for conflict review
const draft = makeSketchDraft("R1", "S1", {
  document: { vertices: [{ id: "v1" }] }, documentVersion: 5,
  baseServerDocument: { vertices: [] }, editMode: "manual_polygon",
});
assert.strictEqual(draft.document_version, 5); ok("draft keeps optimistic token");
assert.deepStrictEqual(draft.document.vertices, [{ id: "v1" }]); ok("draft keeps local document");
assert.deepStrictEqual(draft.base_server_document, { vertices: [] }); ok("draft keeps base server doc for conflict review");
assert.strictEqual(draft.edit_mode, "manual_polygon"); ok("draft keeps edit mode");
const merged = mergeSketchDraft(draft, { document_version: 6 });
assert.strictEqual(merged.document_version, 6); ok("merge updates token");
assert.deepStrictEqual(merged.document.vertices, [{ id: "v1" }]); ok("merge preserves document");

console.log("\nSKETCH CACHE: all " + n + " assertions passed");
