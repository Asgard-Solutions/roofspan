// RC Office/Field compatibility: Field-side gate + offline queue preservation.
// Run: node src/tests/compat.node.test.js
const assert = require("node:assert/strict");
const queue = require("../queue");

function fresh() {
  delete require.cache[require.resolve("../compat")];
  return require("../compat");
}

(async () => {
  // 1) Office version gate (Field 1.1.0 needs Office 0.5.0+)
  let compat = fresh();
  assert.equal(compat.MIN_OFFICE_VERSION, "0.5.0");
  assert.equal(compat.officeTooOld("0.4.8"), true);
  assert.equal(compat.officeTooOld("0.5.0"), false);
  assert.equal(compat.officeTooOld("0.10.0"), false);
  assert.equal(compat.officeTooOld(undefined), true);

  // Office 0.4.8 + Field 1.1.0 -> blocked, names Office as the app to update
  let seen = null;
  compat.onBlocked((b) => { seen = b; });
  assert.equal(await compat.ensureCompatible(async () => ({ status: 200, data: { version: "0.4.8" } })), false);
  assert.deepEqual(seen, { app: "office", officeVersion: "0.4.8" });
  assert.equal(await compat.ensureCompatible(async () => ({ status: 200, data: { version: "0.5.0" } })), false, "stays blocked until retry");
  compat.reset();
  assert.equal(seen, null);

  // Office 0.5.0 + Field 1.1.0 -> ok, cached for the session
  let calls = 0;
  const ok = async () => { calls++; return { status: 200, data: { version: "0.5.0" } }; };
  assert.equal(await compat.ensureCompatible(ok), true);
  assert.equal(await compat.ensureCompatible(ok), true);
  assert.equal(calls, 1);

  // Unreachable Office is not a compatibility decision
  compat = fresh();
  assert.equal(await compat.ensureCompatible(async () => { throw new Error("relay_timeout"); }), null);
  assert.equal(await compat.ensureCompatible(async () => ({ status: 502, data: null })), null);
  assert.equal(compat.getBlocked(), null);
  // An Office without /api/version is older than 0.5.0
  assert.equal(await compat.ensureCompatible(async () => ({ status: 404, data: null })), false);
  assert.equal(compat.getBlocked().app, "office");

  // Office 0.5.0 rejects an outdated Field (426) -> Field update screen
  compat = fresh();
  compat.reportFieldTooOld({ min_supported: "1.1.0" });
  assert.deepEqual(compat.getBlocked(), { app: "field", minField: "1.1.0" });

  // 2) Queue: a 426 keeps the change pending (never failed/dropped) and halts the batch untouched
  const a = queue.makeMutation({ kind: "lead_update", method: "patch", path: "/mobile/leads/1", body: { status: "qualified" } });
  const b = queue.makeMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { outcome: "no_answer" } });
  const sentPaths = [];
  const reject426 = async (m) => { sentPaths.push(m.path); return { status: 426, data: { detail: { code: "must_update", min_supported: "1.1.0" } } }; };
  const out = await queue.processQueue([a, b], reject426);
  assert.equal(out.length, 2);
  assert.equal(out[0].state, "pending");
  assert.equal(out[0].errorCode, "update_required");
  assert.deepEqual(out[0].body, a.body);
  assert.equal(out[0].attempts, 0);
  assert.deepEqual(out[1], b, "items after the 426 are not sent or changed");
  assert.deepEqual(sentPaths, ["/mobile/leads/1"]);

  // 3) Upgrading Field with pending offline changes: rows written by Field 1.0.0 (same storage shape,
  //    incl. one that 1.0.0 marked failed with HTTP 426 against Office 0.5.0) sync after the update.
  const v100Pending = { ...queue.makeMutation({ kind: "lead_update", method: "patch", path: "/mobile/leads/2", body: { status: "interested" } }) };
  const v100Failed426 = { ...queue.makeMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { outcome: "interested" } }),
    state: "failed", error: "HTTP 426", errorCode: "must_update", attempts: 3 };
  const accepted = async (m) => ({ status: 200, data: { id: "srv-" + m.client_id } });
  const after = await queue.processQueue([v100Pending, v100Failed426], accepted);
  assert.deepEqual(after.map((m) => m.state), ["synced", "synced"]);
  assert.equal(after[0].idempotency_key, v100Pending.idempotency_key, "same idempotency key -> no duplicates");

  console.log("PASS compat.node.test.js");
})().catch((e) => { console.error(e); process.exit(1); });
