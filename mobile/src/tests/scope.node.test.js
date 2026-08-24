/*
 * RoofSpan Mobile — P2 offline data foundation pure-logic tests (run in Node, no Expo).
 * Proves: scope namespacing, per-scope queue isolation (user A vs user B, install A vs install B),
 * scoped mutations carry their owner, and unsynced work for other accounts is never dropped.
 * Run: node src/tests/scope.node.test.js
 */
const assert = require("assert");
const { makeScope, scopedKey, forScope, otherScopes } = require("../scope");
const queue = require("../queue");

let passed = 0;
function ok(name, fn) { fn(); passed++; console.log("  ✓", name); }

// ---- scope helpers ----
ok("makeScope combines installation + user", () => {
  assert.strictEqual(makeScope("inst1", "userA"), "inst1::userA");
  assert.strictEqual(makeScope(null, null), "none::anon");
});

ok("scopedKey namespaces cache keys so accounts never collide", () => {
  const a = scopedKey(makeScope("inst1", "userA"), "leads");
  const b = scopedKey(makeScope("inst1", "userB"), "leads");
  const c = scopedKey(makeScope("inst2", "userA"), "leads");
  assert.notStrictEqual(a, b, "different users -> different key");
  assert.notStrictEqual(a, c, "different installs -> different key");
  assert.strictEqual(a, "inst1::userA::leads");
});

// ---- mutations carry their owning scope ----
ok("makeMutation stamps the scope it was created under", () => {
  const m = queue.makeMutation({ kind: "lead", method: "post", path: "/mobile/leads", body: {}, scope: "inst1::userA" });
  assert.strictEqual(m.scope, "inst1::userA");
  assert.strictEqual(m.state, "pending");
  assert.strictEqual(m.idempotency_key, m.client_id);
});

// ---- per-scope isolation of the durable queue (mirrors storage's WHERE scope=? filter) ----
const A = makeScope("inst1", "userA");
const B = makeScope("inst1", "userB");
const store = [
  queue.makeMutation({ kind: "lead", method: "post", path: "/mobile/leads", body: { name: "A1" }, scope: A }),
  queue.makeMutation({ kind: "lead", method: "post", path: "/mobile/leads", body: { name: "A2" }, scope: A }),
  queue.makeMutation({ kind: "lead", method: "post", path: "/mobile/leads", body: { name: "B1" }, scope: B }),
];

ok("user A only ever sees user A's queued work", () => {
  const a = forScope(store, A);
  assert.strictEqual(a.length, 2);
  assert.ok(a.every((m) => m.body.name.startsWith("A")));
});

ok("user B never sees user A's queued work", () => {
  const b = forScope(store, B);
  assert.strictEqual(b.length, 1);
  assert.strictEqual(b[0].body.name, "B1");
});

ok("switching to user B does NOT drop user A's unsynced mutations (§29)", () => {
  const stranded = otherScopes(store, B); // pending work owned by other accounts
  assert.strictEqual(stranded.length, 2, "A's 2 unsynced items are retained, not discarded");
});

ok("legacy (no-scope) mutations fall into the active scope, never orphaned", () => {
  const legacy = queue.makeMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: {} });
  legacy.scope = null;
  const withLegacy = forScope([...store, legacy], A);
  assert.ok(withLegacy.some((m) => m.kind === "visit"), "no-scope item processed under active scope");
});

console.log(`\nSCOPE / OFFLINE-FOUNDATION TESTS: PASS (${passed})`);
process.exit(0);
