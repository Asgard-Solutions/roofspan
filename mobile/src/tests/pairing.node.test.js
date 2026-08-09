/*
 * RoofSpan Mobile — pairing/version/connection pure-logic tests (run in Node).
 * Run: node src/tests/pairing.node.test.js
 */
const assert = require("assert");
const pairing = require("../pairing");
const { versionGate, compareVersions } = require("../version");
const { STATES, mapRelayError, COPY } = require("../connectionState");

let passed = 0;
function ok(name, fn) { fn(); passed++; console.log("  ✓", name); }

console.log("pairing numeric code");
ok("normalizes grouped/spaced input", () => {
  assert.strictEqual(pairing.normalizeNumericCode("728 419"), "728419");
  assert.strictEqual(pairing.normalizeNumericCode("72-84-19x"), "728419");
  assert.strictEqual(pairing.normalizeNumericCode("1234567890"), "123456");
});
ok("validates 6-digit codes", () => {
  assert.strictEqual(pairing.isValidNumericCode("728 419"), true);
  assert.strictEqual(pairing.isValidNumericCode("72841"), false);
  assert.strictEqual(pairing.isValidNumericCode("abcdef"), false);
});
ok("formats grouped for display", () => {
  assert.strictEqual(pairing.formatNumericCode("728419"), "728 419");
  assert.strictEqual(pairing.formatNumericCode("72"), "72");
});

console.log("QR payload validation");
ok("accepts a valid RoofSpan payload", () => {
  const r = pairing.parseQrPayload(JSON.stringify({ v: "1", installation_id: "abc", token: "tok", relay: "wss://r" }));
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.payload.installation_id, "abc");
});
ok("rejects malformed / non-RoofSpan payloads", () => {
  assert.strictEqual(pairing.parseQrPayload("not json").ok, false);
  assert.strictEqual(pairing.parseQrPayload(JSON.stringify({ hello: "world" })).ok, false);
  assert.strictEqual(pairing.parseQrPayload(JSON.stringify({ v: "1", installation_id: "x" })).reason, "invalid");
});
ok("rejects incompatible protocol", () => {
  const r = pairing.parseQrPayload(JSON.stringify({ v: "999", installation_id: "a", token: "t" }));
  assert.strictEqual(r.reason, "protocol");
});
ok("rejects expired payload", () => {
  const r = pairing.parseQrPayload(JSON.stringify({ v: "1", installation_id: "a", token: "t", expires_at: 1 }));
  assert.strictEqual(r.reason, "expired");
});

console.log("version gate");
ok("compares versions", () => {
  assert.strictEqual(compareVersions("1.2.0", "1.10.0"), -1);
  assert.strictEqual(compareVersions("2.0.0", "1.9.9"), 1);
  assert.strictEqual(compareVersions("1.0.0", "1.0.0"), 0);
});
ok("gates must/optional/ok", () => {
  assert.strictEqual(versionGate("1.0.0", "1.2.0", "1.5.0"), "must_update");
  assert.strictEqual(versionGate("1.3.0", "1.2.0", "1.5.0"), "update_available");
  assert.strictEqual(versionGate("1.6.0", "1.2.0", "1.5.0"), "ok");
});

console.log("connection state mapping");
ok("maps relay error codes to user states", () => {
  assert.strictEqual(mapRelayError("subscription_inactive"), STATES.SUBSCRIPTION_INACTIVE);
  assert.strictEqual(mapRelayError("device_auth_failed"), STATES.DEVICE_REVOKED);
  assert.strictEqual(mapRelayError("protocol_mismatch"), STATES.UPDATE_REQUIRED);
  assert.strictEqual(mapRelayError("tunnel_unavailable"), STATES.SERVER_UNAVAILABLE);
});
ok("copy avoids internal jargon", () => {
  const all = JSON.stringify(COPY).toLowerCase();
  ["tunnel", "pub/sub", "reqsig", "websocket", "control plane"].forEach((t) =>
    assert.ok(!all.includes(t), `copy leaked internal term: ${t}`));
});

console.log(`\nPASS ${passed} pairing/version/connection assertions`);
