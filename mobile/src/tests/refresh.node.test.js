/*
 * RoofSpan Mobile — silent session renewal test (runs in Node against the LIVE backend).
 * Proves the fix for "not everything syncs": when a queued mutation is attempted with an EXPIRED /
 * invalid access token, the client silently refreshes the access token using the durable refresh
 * token and retries the SAME request (same idempotency key) — so field work syncs instead of
 * getting stuck on HTTP 401.
 *
 * Run: REACT_APP_BACKEND_URL=http://localhost:8001 node src/tests/refresh.node.test.js
 */
const axios = require("axios");
const queue = require("../queue");

const API = (process.env.REACT_APP_BACKEND_URL || "http://localhost:8001").replace(/\/$/, "") + "/api";
const EMAIL = "pjacobsen@asgardsolution.io";
const PASSWORD = "RoofSpan#Owner2026";

let ACCESS = null;
let REFRESH = null;
let refreshCalls = 0;

// Mirrors src/api.js refreshAccessToken() single-responsibility contract.
async function refreshAccessToken() {
  refreshCalls += 1;
  const r = await axios.post(`${API}/auth/refresh`, { refresh_token: REFRESH }, { validateStatus: () => true });
  if (r.status === 200 && r.data && r.data.access_token) {
    ACCESS = r.data.access_token;
    REFRESH = r.data.refresh_token || REFRESH;
    return true;
  }
  return false;
}

async function sendOnce(m) {
  const headers = { "Idempotency-Key": m.idempotency_key, Authorization: `Bearer ${ACCESS}` };
  if (m.ifMatch) headers["If-Match"] = m.ifMatch;
  const r = await axios.request({ url: API + m.path, method: m.method, data: m.body, headers, validateStatus: () => true });
  return { status: r.status, data: r.data };
}

// Mirrors src/api.js send(): on 401, refresh once and retry.
async function send(m) {
  let res = await sendOnce(m);
  if (res.status === 401 && (await refreshAccessToken())) res = await sendOnce(m);
  return res;
}

function assert(cond, msg) { if (!cond) { console.error("FAIL:", msg); process.exit(1); } console.log("  ✓", msg); }

(async () => {
  const lr = await axios.post(`${API}/auth/login`, { email: EMAIL, password: PASSWORD });
  ACCESS = lr.data.access_token;
  REFRESH = lr.data.refresh_token;
  assert(!!ACCESS && !!REFRESH, "login returns access + refresh tokens");

  // Simulate a session where the access token has expired but the refresh token is still valid.
  const goodAccess = ACCESS;
  ACCESS = goodAccess.slice(0, -6) + "BROKEN"; // corrupt signature -> backend returns 401

  const m = queue.makeMutation({
    kind: "lead_create", method: "post", path: "/mobile/leads",
    body: { name: "Refresh Flow Lead", phone: "555-0100" }, label: "New lead",
  });

  const first = await queue.processMutation(m, send);
  assert(refreshCalls === 1, "a single silent refresh was triggered by the 401");
  assert(first.state === "synced", "queued lead SYNCED after silent refresh (was 401 before)");
  assert(!!first.server_id, "server returned a lead id");

  // Retry with the SAME idempotency key must not create a duplicate.
  const again = await queue.processMutation({ ...m }, send);
  assert(again.state === "synced" && again.server_id === first.server_id,
    "retry with same idempotency key returns the same lead (no duplicate)");

  // A refresh token that is truly invalid must fail closed (no infinite loop, surfaces the 401).
  REFRESH = "not-a-real-refresh-token";
  ACCESS = goodAccess.slice(0, -6) + "BROKEN";
  refreshCalls = 0;
  const m2 = queue.makeMutation({ kind: "lead_create", method: "post", path: "/mobile/leads", body: { name: "Dead Session Lead" } });
  const dead = await queue.processMutation(m2, send);
  assert(refreshCalls === 1, "exactly one refresh attempt when the refresh token is invalid");
  assert(dead.state === "failed" && dead.errorCode === "http_401",
    "with a dead session the mutation surfaces as failed (auth), not synced");

  console.log("\nSILENT SESSION RENEWAL TEST: PASS");
})().catch((e) => { console.error("ERROR", e.response ? e.response.status : e.message); process.exit(1); });
