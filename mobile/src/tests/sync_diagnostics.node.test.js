/* RoofSpan Field — device sync diagnostics (pure Node). */
const { createDiagnostics, buildMutationDiagnostic } = require("../syncDiagnostics");

let failures = 0;
function ok(c, m) { if (c) console.log("  \u2713", m); else { console.error("  \u2717 FAIL:", m); failures++; } }

let t = 0; const now = () => `T${++t}`;
const d = createDiagnostics({ now, capacity: 3 });

// last pull vs last push are tracked SEPARATELY.
d.recordPull(); d.recordPush(); d.recordPull();
let s = d.snapshot();
ok(s.last_successful_pull_at === "T3" && s.last_successful_push_at === "T2", "last successful PULL and PUSH are recorded separately");

// per-mutation record captures the required diagnostic fields.
d.recordMutation({ clientId: "measurement-update:R1", kind: "measurement_update", state: "synced", httpResult: 200, revisionId: "R1", serverToken: "2026-06-01T00:00:00Z", cacheSource: "server_ack" });
s = d.snapshot();
const rec = s.mutations[s.mutations.length - 1];
ok(rec.state === "synced" && rec.http_result === "200" && rec.revision_id === "R1" && rec.server_token === "2026-06-01T00:00:00Z" && rec.cache_source === "server_ack", "mutation diagnostic records state, HTTP result, revision id, server token, and cache source");

// failed mutation keeps its actual error + result.
d.recordMutation({ clientId: "c2", kind: "measurement", state: "failed", httpResult: 422, error: "validation: pitch required", cacheSource: null });
const fail = d.snapshot().mutations.slice(-1)[0];
ok(fail.state === "failed" && fail.http_result === "422" && fail.error === "validation: pitch required", "failed mutation diagnostic keeps the actual HTTP result + error");

// ring buffer is bounded.
d.recordMutation({ clientId: "c3", state: "pending" });
ok(d.snapshot().mutations.length === 3, "per-mutation diagnostic log is bounded to its capacity");

// default http_result is 'ok' when none supplied.
ok(buildMutationDiagnostic({ clientId: "x", state: "synced" }, () => "T").http_result === "ok", "defaults HTTP result to 'ok' when unspecified");

if (failures) { console.error(`\nSYNC DIAGNOSTICS: ${failures} failure(s)`); process.exit(1); }
console.log("\nSYNC DIAGNOSTICS: all passed");
