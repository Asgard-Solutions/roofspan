// RC Office/Field compatibility matrix against REAL Office servers (run by scripts/rc_compat_matrix.sh).
// OFFICE_NEW = current source (0.5.0), OFFICE_OLD = previous release source (0.4.8). Field 1.0.0 is
// emulated by its wire behaviour (no X-RoofSpan-App-Version, legacy statuses); Field 1.1.0 uses the real
// compat gate + queue modules from this source tree.
const assert = require("node:assert/strict");
const queue = require("../mobile/src/queue");
const queue10 = require(process.env.FIELD_OLD_QUEUE || "/tmp/office048/mobile/src/queue");  // previous release queue
const { OFFICE_NEW, OFFICE_OLD, TOKEN_NEW, TOKEN_OLD } = process.env;

function fresh() { delete require.cache[require.resolve("../mobile/src/compat")]; return require("../mobile/src/compat"); }
async function call(base, token, method, path, { headers = {}, body } = {}) {
  const r = await fetch(base + "/api" + path, { method, headers: { Authorization: "Bearer " + token, "content-type": "application/json", ...headers }, body: body ? JSON.stringify(body) : undefined });
  let data = null; try { data = await r.json(); } catch (e) {}
  return { status: r.status, data };
}
const relayed10 = { "X-RoofSpan-Relay-Forwarded": "1" };            // what the 0.5.0 tunnel adds for every device request
const field11 = { "X-RoofSpan-App-Version": "1.1.0" };
const versionOf = (base) => async () => { const r = await fetch(base + "/api/version"); return { status: r.status, data: await r.json() }; };

(async () => {
  const out = [];
  // A) Office 0.4.8 + Field 1.0.0 -> works as before
  let r = await call(OFFICE_OLD, TOKEN_OLD, "GET", "/mobile/leads");
  assert.equal(r.status, 200); out.push("A Office 0.4.8 + Field 1.0.0: read 200 (unchanged)");

  // B) Office 0.5.0 + Field 1.1.0 -> works
  let compat = fresh();
  assert.equal(await compat.ensureCompatible(versionOf(OFFICE_NEW)), true);
  r = await call(OFFICE_NEW, TOKEN_NEW, "GET", "/mobile/leads", { headers: { ...relayed10, ...field11 } });
  assert.equal(r.status, 200); out.push("B Office 0.5.0 + Field 1.1.0: gate ok, read 200");

  // C) Office 0.5.0 + Field 1.0.0 -> rejected before any data operation
  r = await call(OFFICE_NEW, TOKEN_NEW, "GET", "/mobile/leads", { headers: relayed10 });
  assert.equal(r.status, 426);
  const w = await call(OFFICE_NEW, TOKEN_NEW, "POST", "/mobile/leads", { headers: relayed10, body: { name: "RC matrix C must not exist" } });
  assert.equal(w.status, 426);
  out.push(`C Office 0.5.0 + Field 1.0.0: 426 read+write - "${r.data.detail.message}"`);

  // D) Office 0.4.8 + Field 1.1.0 -> Field blocks itself, nothing sent
  compat = fresh();
  assert.equal(await compat.ensureCompatible(versionOf(OFFICE_OLD)), false);
  assert.deepEqual(compat.getBlocked(), { app: "office", officeVersion: "0.4.8" });
  out.push("D Office 0.4.8 + Field 1.1.0: Field shows 'RoofSpan Office needs an update' (Office 0.4.8 < 0.5.0); sync not started");

  // E) Field 1.0.0 queued offline changes, then Field upgraded to 1.1.0 (Office already 0.5.0)
  const c = await call(OFFICE_NEW, TOKEN_NEW, "POST", "/mobile/leads", { headers: field11, body: { name: "RC matrix upgrade lead", status: "new" } });
  assert.equal(c.status, 201);
  const leadId = c.data.id;
  const q10 = [
    queue.makeMutation({ kind: "lead_update", method: "patch", path: `/mobile/leads/${leadId}`, body: { status: "interested", notes: "queued offline in 1.0.0" } }),
  ];
  // Still on 1.0.0 after Office was upgraded: rejected, kept (1.0.0 marks it failed, never deletes it)
  const send10 = (m) => call(OFFICE_NEW, TOKEN_NEW, m.method.toUpperCase(), m.path, { headers: { ...relayed10, "Idempotency-Key": m.idempotency_key }, body: m.body });
  let after = await queue10.processQueue(q10, send10);
  assert.equal(after[0].state, "failed"); assert.equal(after[0].errorCode, "must_update");   // 1.0.0: kept as failed, retried
  assert.deepEqual(after[0].body, q10[0].body);
  let lead = await call(OFFICE_NEW, TOKEN_NEW, "GET", `/mobile/leads/${leadId}`, { headers: field11 });
  assert.equal(lead.data.status, "new", "no partial write");
  // Upgraded to 1.1.0: same stored row replays and lands (legacy 'interested' -> 'qualified')
  compat = fresh();
  assert.equal(await compat.ensureCompatible(versionOf(OFFICE_NEW)), true);
  const send11 = (m) => call(OFFICE_NEW, TOKEN_NEW, m.method.toUpperCase(), m.path, { headers: { ...relayed10, ...field11, "Idempotency-Key": m.idempotency_key }, body: m.body });
  after = await queue.processQueue(after, send11);
  assert.equal(after[0].state, "synced");
  lead = await call(OFFICE_NEW, TOKEN_NEW, "GET", `/mobile/leads/${leadId}`, { headers: field11 });
  assert.equal(lead.data.status, "qualified");
  assert.equal(lead.data.notes, "queued offline in 1.0.0");
  out.push("E Field 1.0.0 -> 1.1.0 with pending change: 1.0.0 keeps it (failed, not deleted), 1.1.0 replays it (interested -> qualified)");
  console.log(out.join("\n"));
  console.log("LEAD_ID=" + leadId);
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
