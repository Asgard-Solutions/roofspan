/*
 * RoofSpan Mobile — offline sync lifecycle test (runs in Node against the LIVE backend).
 * Proves the required field lifecycle for the pure queue core (src/queue.js):
 *   create offline -> persist to disk -> restart (reload) -> retry with SAME idempotency key
 *   -> server accepts once -> marked Synced -> Office sees exactly one record (no duplicate).
 *
 * Run: node src/tests/sync.node.test.js
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const axios = require("axios");
const queue = require("../queue");

const API = (process.env.REACT_APP_BACKEND_URL || "https://unified-mono-deploy.preview.emergentagent.com").replace(/\/$/, "") + "/api";
const EMAIL = "pjacobsen@asgardsolution.io";
const PASSWORD = "RoofSpan#Owner2026";
const DEVICE_FILE = path.join(os.tmpdir(), "roofspan_mobile_pending.json");

let TOKEN = null;
// send() adapter identical in spirit to the app's api.send (Idempotency-Key + If-Match, never throws on status).
async function send(m) {
  const headers = { "Idempotency-Key": m.idempotency_key, Authorization: `Bearer ${TOKEN}` };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;
  return axios.request({ url: API + m.path, method: m.method, data: m.body, headers, validateStatus: () => true });
}
const persist = (items) => fs.writeFileSync(DEVICE_FILE, JSON.stringify(items));
const reload = () => (fs.existsSync(DEVICE_FILE) ? JSON.parse(fs.readFileSync(DEVICE_FILE, "utf8")) : []);

function assert(cond, msg) { if (!cond) { console.error("FAIL:", msg); process.exit(1); } console.log("  ✓", msg); }

(async () => {
  // login
  const lr = await axios.post(`${API}/auth/login`, { email: EMAIL, password: PASSWORD });
  TOKEN = lr.data.access_token;
  assert(!!TOKEN, "logged in");

  // a property to attach the field visit to
  const pr = await axios.post(`${API}/properties`, { address_line1: "9 Sync Test Rd", city: "Austin", state: "TX", zip_code: "78701", latitude: 30.27, longitude: -97.74 }, { headers: { Authorization: `Bearer ${TOKEN}` } });
  const PID = pr.data.id;
  const NOTE = "offline-sync-" + Date.now();

  // 1. Create while OFFLINE (do not send yet) and persist to device storage.
  const m = queue.makeMutation({ kind: "visit", method: "post", path: "/mobile/visits", body: { property_id: PID, outcome: "no_answer", notes: NOTE } });
  persist([m]);
  assert(m.state === "pending" && m.idempotency_key === m.client_id, "created pending mutation with stable idempotency key");

  // 2. RESTART the app: forget in-memory state, reload from disk.
  let items = reload();
  assert(items.length === 1 && items[0].state === "pending" && items[0].client_id === m.client_id, "pending write survived restart with same identity");
  const keyBefore = items[0].idempotency_key;

  // 3. Reconnect + sync (first attempt).
  items = await queue.processQueue(items, send);
  persist(items);
  assert(items[0].state === "synced", "first sync -> Synced");
  assert(items[0].idempotency_key === keyBefore, "idempotency key NOT regenerated on sync");
  const serverId = items[0].server_id;
  assert(!!serverId, "server returned an id");

  // 4. Simulate a duplicate retry (e.g. flaky network) by forcing pending again — SAME key.
  items[0].state = "pending";
  persist(items);
  items = await queue.processQueue(reload(), send);
  persist(items);
  assert(items[0].state === "synced" && items[0].server_id === serverId, "retry with same key -> same server id (server accepted once)");

  // 5. Office/authoritative check: exactly ONE visit with our note exists on the property.
  const det = await axios.get(`${API}/properties/${PID}`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  const matches = (det.data.visits || []).filter((v) => v.notes === NOTE);
  assert(matches.length === 1, `Office shows exactly one visit (no duplicate) — found ${matches.length}`);

  // 6. Conflict behavior: create inspection, then update with a stale If-Match -> Conflict (pending data preserved).
  const insp = queue.makeMutation({ kind: "inspection", method: "post", path: "/mobile/inspections", body: { property_id: PID, roof_condition: "fair", findings: "test" } });
  let ins = await queue.processQueue([insp], send);
  assert(ins[0].state === "synced", "inspection created + synced");
  const staleUpd = queue.makeMutation({ kind: "inspection_update", method: "patch", path: `/mobile/inspections/${ins[0].server_id}`, body: { findings: "stale" }, ifMatch: "1999-01-01T00:00:00+00:00" });
  let updRes = await queue.processQueue([staleUpd], send);
  assert(updRes[0].state === "conflict", "stale update surfaces as Conflict (not overwrite)");
  assert(updRes[0].body.findings === "stale", "user's pending field data preserved on conflict");

  console.log("\nSYNC LIFECYCLE TEST: PASS");
  fs.unlinkSync(DEVICE_FILE);
  process.exit(0);
})().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
