const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const queue = require("../queue");

test("Relay photo transport uses the SDK-54 legacy FileSystem API for readAsStringAsync", () => {
  const src = fs.readFileSync(path.join(__dirname, "..", "transport.js"), "utf8");
  assert.match(src, /from\s+["']expo-file-system\/legacy["']/, "Relay transport must import expo-file-system/legacy");
  assert.doesNotMatch(src, /from\s+["']expo-file-system["']/, "bare expo-file-system import must not be used with readAsStringAsync");
});

test("local photo validation caps files at a Relay-safe 8 MiB before base64 encoding", () => {
  assert.strictEqual(typeof queue.validateLocalPhotoInfo, "function", "queue.validateLocalPhotoInfo must exist");
  assert.deepStrictEqual(queue.validateLocalPhotoInfo({ exists: true, size: 1024 }), { ok: true });
  const tooLarge = queue.validateLocalPhotoInfo({ exists: true, size: 8 * 1024 * 1024 + 1 });
  assert.strictEqual(tooLarge.ok, false);
  assert.strictEqual(tooLarge.status, 413);
  assert.strictEqual(tooLarge.code, "http_413");
  assert.strictEqual(queue.isPermanentFailure({ state: "failed", kind: "photo", photo: {}, errorCode: tooLarge.code }), true);
});
