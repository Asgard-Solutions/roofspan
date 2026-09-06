/* RoofSpan Field — device sync diagnostics (pure Node). */
const { createDiagnostics, buildMutationDiagnostic } = require("../syncDiagnostics");

let failures = 0;
function ok(c, m) { if (c) console.log("  \u2713", m); else { console.error("  \u2717 FAIL:", m); failures++; } }

let t = 0; const now = () => `T${++t}`;
const d = createDiagnostics({ now, capacity: 3 });

// last pull vs push ATTEMPT vs push SUCCESS are tracked SEPARATELY (a failed attempt must not advance
// last_successful_push_at).
d.recordPull(); d.recordPushAttempt(); d.recordPull();
let s = d.snapshot();
ok(s.last_successful_pull_at === "T3" && s.last_push_attempt_at === "T2" && s.last_successful_push_at === null,
   "a push ATTEMPT sets last_push_attempt_at but NOT last_successful_push_at");
d.recordPushSuccess();
s = d.snapshot();
ok(s.last_successful_push_at === "T4", "last_successful_push_at advances ONLY on an acknowledged push");

// per-mutation record captures the required diagnostic fields (incl. path category, http status,
// relay error code, mutation generation, recovery action).
d.recordMutation({ clientId: "measurement-update:R1", kind: "measurement_update", state: "synced", httpResult: 200, httpStatus: 200, pathCategory: "/api/measurements", mutationGeneration: 3, revisionId: "R1", serverToken: "2026-06-01T00:00:00Z", cacheSource: "server_ack", recoveryAction: "retire" });
s = d.snapshot();
const rec = s.mutations[s.mutations.length - 1];
ok(rec.state === "synced" && rec.http_status === 200 && rec.path_category === "/api/measurements" && rec.mutation_generation === 3 && rec.revision_id === "R1" && rec.server_token === "2026-06-01T00:00:00Z" && rec.cache_source === "server_ack" && rec.recovery_action === "retire", "mutation diagnostic records state, http status, path category, generation, revision id, server token, cache source, recovery action");

// PRIVACY: even if a caller passes secrets/PII, the record must never surface unknown fields.
d.recordMutation({ clientId: "c9", state: "pending", accessToken: "SECRET", deviceCredential: "CRED", notes: "homeowner is elderly", photo: "<<base64>>" });
const priv = d.snapshot().mutations.slice(-1)[0];
ok(priv.accessToken === undefined && priv.deviceCredential === undefined && priv.notes === undefined && priv.photo === undefined, "diagnostic record NEVER includes tokens, credentials, notes, or photo payloads");

// hydrate() restores a persisted snapshot after an app kill/restart.
const d2 = createDiagnostics({ now, capacity: 3 });
d2.hydrate({ last_push_attempt_at: "P1", last_successful_push_at: "P2", last_successful_pull_at: "P3", mutations: [{ client_id: "old", state: "failed" }] });
const h = d2.snapshot();
ok(h.last_push_attempt_at === "P1" && h.last_successful_push_at === "P2" && h.last_successful_pull_at === "P3" && h.mutations.length === 1 && h.mutations[0].client_id === "old", "hydrate() restores persisted timestamps + ring (survives restart)");

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
