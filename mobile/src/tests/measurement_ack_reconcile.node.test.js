/* RoofSpan Field — measurement acknowledgement lifecycle + explicit state table (pure Node). */
const mr = require("../measurementReconcile");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

// ---------------- Explicit mutation state table (item #2) ----------------
ok(mr.measurementSyncState(null, false).status === "Synced", "no mutation → Office/server is authoritative (Synced)");
ok(mr.measurementSyncState({ state: "pending" }, false).status === "Waiting to sync", "pending → Waiting to sync");
ok(mr.measurementSyncState({ state: "pending" }, true).status === "Syncing", "pending while syncing → Synchronizing");
ok(mr.measurementSyncState({ state: "synced" }, false).status === "Synced", "synced → Synced");
const failSt = mr.measurementSyncState({ state: "failed", error: "HTTP 422 — validation" }, false);
ok(failSt.status === "Sync failed — retry needed" && failSt.failed === true, "failed → Sync failed (never 'waiting')");
ok(failSt.reason === "HTTP 422 — validation", "failed carries the ACTUAL reason for the rep");
const confSt = mr.measurementSyncState({ state: "conflict", error: "changed on server" }, false);
ok(confSt.status === "Conflict — review required" && confSt.conflict === true, "conflict → Conflict — review required");
ok(mr.measurementSyncState({ state: "locked" }, false).locked === true, "locked → locked (new-revision path)");

// ---------------- Scoped measurement-list upsert (ack step b) ----------------
const list0 = [{ id: "r1", revision_number: 1, updated_at: "t1" }];
const up1 = mr.upsertRevision(list0, { id: "r1", revision_number: 1, updated_at: "t2", status: "field_complete" });
ok(up1.length === 1 && up1[0].updated_at === "t2" && up1[0].status === "field_complete", "upsert UPDATES the existing revision in place");
const up2 = mr.upsertRevision(list0, { id: "r2", revision_number: 2, updated_at: "t3" });
ok(up2.length === 2 && up2.find((r) => r.id === "r2"), "upsert INSERTS a new revision, preserving the others");
ok(mr.upsertRevision(null, { id: "r9" }).length === 1, "upsert tolerates a missing list");
ok(mr.upsertRevision([{ id: "r1" }], {}).length === 1, "upsert with no server id is a no-op");

// ---------------- Scope extraction from the mutation body ----------------
ok(mr.measScopeFromBody({ lead_id: "l1", structures: [] }).lead_id === "l1", "scope derived from body.lead_id");
ok(mr.measScopeFromBody({ property_id: "p1" }).property_id === "p1", "scope derived from body.property_id");
ok(mr.measScopeFromBody({}) === null, "no scope in body → null (skip list write)");

// ---------------- Supersession safety (a late ack must not delete newer work) ----------------
ok(mr.isSupersededAck({ mutation_generation: 3 }, { mutation_generation: 2 }) === true, "newer stored generation → ack is superseded");
ok(mr.isSupersededAck({ mutation_generation: 2 }, { mutation_generation: 2 }) === false, "same generation → matched ack");
ok(mr.isSupersededAck(null, { mutation_generation: 2 }) === false, "gone row → treated as matched (no newer work)");

// ---------------- Create-draft retirement (ack step c) ----------------
ok(mr.retireCreateDraft({ client_id: "c1" }, "c1") === null, "create draft retired when client_id matches the ack");
const keep = { client_id: "c2" };
ok(mr.retireCreateDraft(keep, "c1") === keep, "create draft PRESERVED when a different client_id (newer draft) exists");
ok(mr.retireCreateDraft(null, "c1") === null, "no draft → nothing to retire");

// ---------------- Working-draft ack (ack step: same generation, no newer edit) ----------------
const emptyCreateWd = { working: true, local_client_id: "c1", structures: [], facets: [], edges: [], pens: [], summary: {} };
ok(mr.planMeasurementWorkingAck(emptyCreateWd, { kind: "measurement", clientId: "c1" }) === null, "empty create working draft belonging to the ack is retired");
const contentWd = { working: true, local_client_id: "c1", structures: [{ ref: "s1" }], facets: [], edges: [], pens: [], summary: {} };
ok(mr.planMeasurementWorkingAck(contentWd, { kind: "measurement", clientId: "c1" }) === contentWd, "a CONTENT-bearing working draft (newer edit) is NEVER deleted by an ack");
const otherWd = { working: true, local_client_id: "cX", structures: [], facets: [], edges: [], pens: [], summary: {} };
ok(mr.planMeasurementWorkingAck(otherWd, { kind: "measurement", clientId: "c1" }) === otherWd, "a working draft for a DIFFERENT client is preserved");
const emptyUpdateWd = { working: true, base: { id: "r1", if_match: "t1" }, structures: [], facets: [], edges: [], pens: [], summary: {} };
ok(mr.planMeasurementWorkingAck(emptyUpdateWd, { kind: "measurement_update", revisionId: "r1" }) === null, "empty update working draft for the acked revision is retired");

// ---------------- resolveMeasurementView: full state table (items #1 + #3) ----------------
// create pending
let v = mr.resolveMeasurementView({ draft: { body: {} }, pendingCreate: { state: "pending" }, isSyncing: false });
ok(v.kind === "local_draft" && v.status === "Waiting to sync", "unacked create shows the local draft, waiting to sync");
// create failed
v = mr.resolveMeasurementView({ draft: { body: {} }, pendingCreate: { state: "failed", error: "boom" }, isSyncing: false });
ok(v.kind === "local_draft" && v.failed === true && v.reason === "boom", "failed create preserves the draft and shows the failure reason");
// create acknowledged → falls through to authoritative server
v = mr.resolveMeasurementView({ draft: { body: {} }, pendingCreate: { state: "synced" }, serverDetail: { id: "r1", updated_at: "t1" }, serverStale: false });
ok(v.kind === "server" && v.status === "Synced", "acknowledged create yields the authoritative Office revision");

// update pending (server unchanged) → local wins, waiting
v = mr.resolveMeasurementView({ optimistic: { id: "r1", updated_at: "t1" }, pendingUpdate: { state: "pending", ifMatch: "t1" }, serverDetail: { id: "r1", updated_at: "t1" }, serverStale: false, isSyncing: false });
ok(v.kind === "local_update" && v.status === "Waiting to sync", "pending update with unchanged server → local optimistic wins");
// update pending (Office changed the SAME revision) → soft conflict
v = mr.resolveMeasurementView({ optimistic: { id: "r1", updated_at: "t1" }, pendingUpdate: { state: "pending", ifMatch: "t1" }, serverDetail: { id: "r1", updated_at: "t2" }, serverStale: false });
ok(v.kind === "conflict" && v.conflict === true && v.serverDetail.updated_at === "t2", "pending update + Office change → conflict with the server copy");
// update failed
v = mr.resolveMeasurementView({ optimistic: { id: "r1" }, pendingUpdate: { state: "failed", ifMatch: "t1", error: "HTTP 500" }, serverDetail: { id: "r1", updated_at: "t1" }, serverStale: false });
ok(v.kind === "local_update" && v.failed === true && v.status === "Sync failed — retry needed" && v.reason === "HTTP 500", "failed update preserves local work + shows reason (item #2)");
// update DURABLE 409 conflict — the review uses the mutation's PERSISTED serverValue (item #3)
const persistedServer = { id: "r1", updated_at: "t9", structures: [{ ref: "office" }] };
v = mr.resolveMeasurementView({ optimistic: { id: "r1", updated_at: "t1" }, pendingUpdate: { state: "conflict", ifMatch: "t1", serverValue: persistedServer, error: "changed on server" }, serverDetail: null, serverStale: true });
ok(v.kind === "conflict" && v.serverDetail === persistedServer, "durable 409 conflict surfaces the mutation's persisted serverValue for review (item #3)");
// update locked
v = mr.resolveMeasurementView({ optimistic: { id: "r1" }, pendingUpdate: { state: "locked", ifMatch: "t1" }, serverDetail: { id: "r1", updated_at: "t1", editable: false }, serverStale: false });
ok(v.kind === "locked" && v.locked === true, "locked update shows the server revision as locked (new-revision path)");
// synced update → authoritative server (not the stale optimistic)
v = mr.resolveMeasurementView({ optimistic: { id: "r1", updated_at: "t1" }, pendingUpdate: { state: "synced" }, serverDetail: { id: "r1", updated_at: "t9" }, serverStale: false });
ok(v.kind === "server" && v.detail.updated_at === "t9", "an acknowledged update yields the authoritative Office revision, not the optimistic copy");

if (failures) { console.error(`\nMEASUREMENT ACK RECONCILE: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT ACK RECONCILE: all passed");
