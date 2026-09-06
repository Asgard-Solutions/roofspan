/* RoofSpan Field — measurement sync ACCEPTANCE CONDITIONS expressed against the pure decision layer.
 * These assert the invariants the reported bug requires; the durable IO paths that consume them are wired
 * in sync.js (not Node-runnable) and are exercised on-device. */
const { measurementSyncState, resolveMeasurementView, retireCreateDraft, isSupersededAck } = require("../measurementReconcile");
const { classifyOrphanWorkingDraft, planStartupRecovery, recoveryAttentionItem } = require("../measurementRecovery");

let failures = 0;
function ok(c, m) { if (c) console.log("  \u2713", m); else { console.error("  \u2717 FAIL:", m); failures++; } }

// AC: No screen displays "Waiting to sync" when the matching mutation is SYNCED.
ok(measurementSyncState({ state: "synced" }, false).status === "Synced", "synced mutation → Synced (never Waiting to sync)");
let v = resolveMeasurementView({ optimistic: { id: "R1", updated_at: "t1" }, pendingUpdate: { state: "synced" }, serverDetail: { id: "R1", updated_at: "t9" }, serverStale: false });
ok(v.kind === "server" && v.status === "Synced", "acknowledged update view shows the authoritative Office revision, not Waiting to sync");

// AC: No screen displays "Waiting to sync" for a TERMINAL FAILED mutation.
ok(measurementSyncState({ state: "failed", error: "HTTP 422" }, false).status === "Sync failed — retry needed", "failed mutation → Sync failed — retry needed");
v = resolveMeasurementView({ optimistic: { id: "R1" }, pendingUpdate: { state: "failed", ifMatch: "t1", error: "HTTP 422" }, serverDetail: { id: "R1", updated_at: "t1" }, serverStale: false });
ok(v.status === "Sync failed — retry needed" && v.failed === true, "failed update view is failed, never waiting");

// AC: A successful create acknowledgement retires the matching local draft.
ok(retireCreateDraft({ client_id: "c1" }, "c1") === null, "create ack retires the matching local draft");
const keep = { client_id: "c2" };
ok(retireCreateDraft(keep, "c1") === keep, "a create ack never retires a DIFFERENT (newer) draft");

// AC: No legitimate local edits are discarded without ack or explicit user selection.
ok(isSupersededAck({ mutation_generation: 3 }, { mutation_generation: 2 }) === true, "a late ack for an older generation is superseded → newer local work is preserved");
const contentWd = { working: true, base: { id: "R1", if_match: "t1" }, structures: [{ ref: "s1" }], facets: [], edges: [], pens: [], summary: {} };
ok(classifyOrphanWorkingDraft({ wd: contentWd, hasActiveMutation: false, baseRevision: { id: "R1", updated_at: "t1", structures: [], penetrations: [] } }).action === "keep", "a content-bearing working draft (Office not advanced) is never silently deleted");

// AC: An acknowledged measurement remains correct after restart; a mobile upgrade repairs stranded drafts.
const mutations = [
  { kind: "measurement", state: "synced", client_id: "c-syncedcreate", serverValue: { id: "R1", updated_at: "t1" }, body: { lead_id: "L1" }, mutation_generation: 1 },
  { kind: "measurement_update", state: "failed", client_id: "measurement-update:R2", body: { lead_id: "L2" }, error: "HTTP 500" },
  { kind: "measurement_update", state: "conflict", client_id: "measurement-update:R3", serverValue: { id: "R3", updated_at: "t9" }, body: { lead_id: "L3" }, error: "changed on server" },
  { kind: "measurement", state: "pending", client_id: "c-pending", body: { lead_id: "L4" } },
];
const plan = planStartupRecovery(mutations);
ok(plan.settle.length === 1 && plan.settle[0].client_id === "c-syncedcreate", "startup recovery settles the synced create (so its stranded draft is retired on restart)");
ok(plan.failures.length === 1 && plan.failures[0].kind === "failed" && plan.failures[0].revisionId === "R2", "startup recovery surfaces the failed mutation for review");
ok(plan.conflicts.length === 1 && plan.conflicts[0].kind === "conflict" && plan.conflicts[0].revisionId === "R3", "startup recovery surfaces the persisted conflict for review");
ok(!plan.settle.some((m) => m.client_id === "c-pending") && !plan.failures.some((f) => f.client_id === "c-pending"), "a still-pending mutation is left untouched by startup recovery");
// the settled synced create's draft is then retired by the caller
ok(retireCreateDraft({ client_id: "c-syncedcreate" }, plan.settle[0].client_id) === null, "the settled synced create's matching draft is retired on restart (not the local draft shown)");

if (failures) { console.error(`\nMEASUREMENT ACCEPTANCE: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT ACCEPTANCE: all passed");
