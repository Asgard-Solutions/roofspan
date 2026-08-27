/*
 * RoofSpan Mobile — durable photo queue + offline photo lifecycle regression tests.
 * Runs in Node against the PURE queue core (src/queue.js) with a mock multipart backend.
 *
 * Reproduces the confirmed defect (photo metadata dropped by makeMutation -> crash + HTTP 422 JSON
 * fallthrough) and proves the fix end-to-end through: capture -> queue -> SQLite-style serialize ->
 * restart (reload) -> multipart transport -> backend 201 -> synced -> idempotent retry (no dupes),
 * plus that a malformed legacy photo row can never crash the flow.
 *
 * Run: node --test src/tests/photo.node.test.js
 */
const { test } = require("node:test");
const assert = require("node:assert");
const os = require("os");
const path = require("path");
const fs = require("fs");
const queue = require("../queue");

const PHOTO = { uri: "file:///some/path/photo.jpg", name: "photo.jpg", type: "image/jpeg" };

// ---- Phase 1/2: photo metadata survives mutation creation ----
test("makeMutation persists photo.uri/name/type (regression for dropped photo)", () => {
  const m = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: { record_id: "r1" }, photo: { ...PHOTO } });
  assert.ok(m.photo, "photo must be present on the mutation");
  assert.strictEqual(m.photo.uri, PHOTO.uri);
  assert.strictEqual(m.photo.name, PHOTO.name);
  assert.strictEqual(m.photo.type, PHOTO.type);
  assert.strictEqual(m.idempotency_key, m.client_id, "idempotency key unchanged");
});

test("photo metadata survives SQLite-style serialize + reload", () => {
  const m = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: { record_id: "r1" }, photo: { ...PHOTO } });
  const reloaded = JSON.parse(JSON.stringify(m)); // mirrors storage.enqueue JSON round-trip
  assert.deepStrictEqual(reloaded.photo, PHOTO);
});

// ---- Phase 2: transport decision (never JSON fallthrough for photos) ----
test("buildSendPlan: valid photo -> multipart, malformed photo -> local_failure, other -> json", () => {
  const good = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: {}, photo: { ...PHOTO } });
  assert.strictEqual(queue.buildSendPlan(good).transport, "multipart");

  const malformed = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: {}, photo: null });
  const plan = queue.buildSendPlan(malformed);
  assert.strictEqual(plan.transport, "local_failure");
  assert.strictEqual(plan.code, "photo_file_missing");

  const badType = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: {}, photo: { uri: "x", name: "x.gif", type: "image/gif" } });
  assert.strictEqual(queue.buildSendPlan(badType).code, "photo_unsupported_type");

  const json = queue.makeMutation({ kind: "lead", method: "post", path: "/mobile/leads", body: { a: 1 } });
  assert.strictEqual(queue.buildSendPlan(json).transport, "json");
});

// Mock multipart backend with Idempotency-Key dedup (mirrors Office /api/mobile/photos + api.send).
function makeBackend() {
  const byKey = new Map();
  const photos = [];
  async function send(m) {
    const plan = queue.buildSendPlan(m);
    if (plan.transport === "local_failure") return { status: plan.status, data: { detail: { code: plan.code, message: plan.message } } };
    assert.strictEqual(plan.transport, "multipart", "photo mutation must transport as multipart, not JSON");
    assert.ok(m.photo && m.photo.uri && m.photo.name && m.photo.type, "multipart send must carry file metadata");
    if (byKey.has(m.idempotency_key)) return { status: 201, data: { id: byKey.get(m.idempotency_key) } };
    const id = `photo_${photos.length + 1}`;
    byKey.set(m.idempotency_key, id);
    photos.push({ id, name: m.photo.name, type: m.photo.type });
    return { status: 201, data: { id } };
  }
  return { send, photos, byKey };
}

// ---- Phase 9: full offline photo lifecycle ----
test("offline photo lifecycle: queue -> restart -> multipart upload -> 201 synced -> idempotent retry", async () => {
  const backend = makeBackend();
  const file = path.join(os.tmpdir(), `rs_photo_queue_${Date.now()}.json`);

  // 1-5: capture -> mutation with photo -> persist to disk (SQLite stand-in)
  const created = queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: { record_type: "job", record_id: "job1", category: "Roof" }, photo: { ...PHOTO } });
  fs.writeFileSync(file, JSON.stringify([created]));

  // 6-7: simulate app restart — reload from disk, metadata intact
  const reloaded = JSON.parse(fs.readFileSync(file, "utf8"));
  assert.deepStrictEqual(reloaded[0].photo, PHOTO, "photo metadata survives restart");

  // 8-15: sync processes as multipart, backend 201, becomes synced with server_id
  let processed = await queue.processQueue(reloaded, backend.send);
  fs.writeFileSync(file, JSON.stringify(processed));
  assert.strictEqual(processed[0].state, "synced");
  assert.strictEqual(processed[0].server_id, "photo_1");

  // 16-17: retry the SAME idempotency key -> no duplicate Photo record
  const retryItem = { ...processed[0], state: "pending" }; // force a retry with same client_id/key
  await queue.processQueue([retryItem], backend.send);
  assert.strictEqual(backend.photos.length, 1, "duplicate retry must not create a second photo");
  fs.unlinkSync(file);
});

// ---- Malformed legacy row must not crash + is a deterministic permanent failure ----
test("malformed legacy photo mutation fails deterministically (no crash, no JSON send)", async () => {
  const backend = makeBackend();
  const legacy = { ...queue.makeMutation({ kind: "photo", method: "post", path: "/mobile/photos", body: { record_id: "r1" } }), photo: undefined, state: "failed", error: "HTTP 422" };
  const [out] = await queue.processQueue([legacy], backend.send);
  assert.strictEqual(out.state, "failed");
  assert.strictEqual(out.errorCode, "photo_file_missing");
  assert.strictEqual(out.error, "Photo file unavailable");
  assert.strictEqual(backend.photos.length, 0, "malformed item must never reach the backend as a photo");
});

// ---- Auto-retry backoff classification ----
test("isPermanentFailure: local photo issues are permanent; transient photo/backend hiccups are retryable", () => {
  const perm = { state: "failed", kind: "photo", photo: {}, errorCode: "photo_file_missing" };
  assert.strictEqual(queue.isPermanentFailure(perm), true);
  assert.strictEqual(queue.isPermanentFailure({ state: "failed", kind: "photo", photo: {}, errorCode: "http_413" }), true);
  // a transient/backend-side photo failure is safe to auto-retry
  assert.strictEqual(queue.isPermanentFailure({ state: "failed", kind: "photo", photo: {}, errorCode: "http_422" }), false);
  // pending items are never "permanent failures"
  assert.strictEqual(queue.isPermanentFailure({ state: "pending", kind: "photo", photo: {} }), false);
});
