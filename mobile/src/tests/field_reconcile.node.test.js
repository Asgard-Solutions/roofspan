"use strict";
// Field Property/Map cache synchronization (reconciliation) contracts. Exercises the SAME pure reducers
// the sync engine uses on acknowledgement (fieldReconcile.js) plus a faithful in-memory mirror of
// sync._reconcileFieldAcks gating (only SYNCED Property/Visit/DNK/Lead rows reconcile; pending untouched).
const assert = require("assert");
const R = require("../fieldReconcile");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

// In-memory cache double + a mirror of the sync ack-reconciliation loop.
function makeCaches(initial) { return JSON.parse(JSON.stringify(initial)); }
function sectionNames(caches) { return Object.keys(caches).filter((k) => k.startsWith("section:") && k.endsWith(":props")); }
function reconcileLoop(caches, processed) {
  const KINDS = new Set(["visit", "property_patch", "lead_create"]);
  for (const m of processed) {
    if (m.state !== "synced" || !KINDS.has(m.kind)) continue;   // pending/failed/conflict + other kinds skipped
    const pid = R.propertyIdForMutation(m);
    if (!pid) continue;
    const dk = `property:${pid}`;
    caches[dk] = R.reconcilePropertyDetail(m.kind, m.serverValue || null, caches[dk]);
    for (const name of sectionNames(caches)) {
      caches[name] = R.reconcileCanvassFeatures(m.kind, m.serverValue || null, pid, caches[name]);
    }
  }
  return caches;
}
const featureColl = (props) => ({ type: "FeatureCollection", features: props.map((p) => ({ type: "Feature", geometry: {}, properties: p })) });
const feat = (coll, id) => coll.features.find((f) => f.properties.id === id).properties;

// ---- 1. optimistic visit cache update (detail + canvass, pre-ack) ----
{
  const detail = { id: "P1", visits: [] };
  const optDetail = { ...detail, visits: [{ id: "pending-1", outcome: "interested", visited_at: "T0" }], last_outcome: "interested", last_visited_at: "T0" };
  assert.strictEqual(optDetail.visits[0].id, "pending-1");
  const coll = R.optimisticCanvassPatch("P1", { last_outcome: "interested", last_visited_at: "T0" }, featureColl([{ id: "P1" }, { id: "P2" }]));
  assert.strictEqual(feat(coll, "P1").last_outcome, "interested");
  assert.strictEqual(feat(coll, "P2").last_outcome, undefined, "other property untouched");
  ok("optimistic visit updates the property detail + only its own canvass feature");
}

// ---- 2. authoritative visit acknowledgement reconciliation ----
{
  const cur = { id: "P1", visits: [{ id: "pending-1", outcome: "interested", visited_at: "T0" }] };
  const sv = { id: "V9", property_id: "P1", outcome: "interested", notes: "quote", visited_at: "T1", user_email: "rep@x" };
  const next = R.reconcilePropertyDetail("visit", sv, cur);
  assert.strictEqual(next.visits.length, 1, "optimistic placeholder replaced (not duplicated)");
  assert.strictEqual(next.visits[0].id, "V9");
  assert.strictEqual(next.last_outcome, "interested"); assert.strictEqual(next.last_visited_at, "T1");
  ok("authoritative visit ack replaces the pending placeholder and sets last_outcome/last_visited_at");
}

// ---- 3 & 4. optimistic DNK ON + authoritative DNK ON reconciliation ----
{
  let coll = R.optimisticCanvassPatch("P1", { do_not_knock: true }, featureColl([{ id: "P1", do_not_knock: false }]));
  assert.strictEqual(feat(coll, "P1").do_not_knock, true, "optimistic DNK ON on the map");
  const sv = { id: "P1", do_not_knock: true, do_not_knock_reason: "Owner asked", owner_occupied: true, lead_id: null, visits: [{ outcome: "do_not_knock", visited_at: "T2" }] };
  const detail = R.reconcilePropertyDetail("property_patch", sv, { id: "P1", do_not_knock: false });
  assert.strictEqual(detail.do_not_knock, true); assert.strictEqual(detail.do_not_knock_reason, "Owner asked");
  coll = R.reconcileCanvassFeatures("property_patch", sv, "P1", coll);
  assert.strictEqual(feat(coll, "P1").do_not_knock, true);
  assert.strictEqual(feat(coll, "P1").owner_occupied, true);
  assert.strictEqual(feat(coll, "P1").has_lead, false);
  ok("DNK ON: optimistic map + authoritative detail/canvass reconciliation");
}

// ---- 5. optimistic DNK OFF + authoritative DNK OFF reconciliation ----
{
  let coll = R.optimisticCanvassPatch("P1", { do_not_knock: false }, featureColl([{ id: "P1", do_not_knock: true }]));
  assert.strictEqual(feat(coll, "P1").do_not_knock, false, "optimistic DNK OFF on the map");
  const sv = { id: "P1", do_not_knock: false, do_not_knock_reason: null, owner_occupied: false, lead_id: null, visits: [] };
  const detail = R.reconcilePropertyDetail("property_patch", sv, { id: "P1", do_not_knock: true, do_not_knock_reason: "old" });
  assert.strictEqual(detail.do_not_knock, false); assert.strictEqual(detail.do_not_knock_reason, null);
  coll = R.reconcileCanvassFeatures("property_patch", sv, "P1", coll);
  assert.strictEqual(feat(coll, "P1").do_not_knock, false);
  ok("DNK OFF: optimistic map + authoritative detail/canvass reconciliation");
}

// ---- 6. Property cache update: property_patch replaces the whole authoritative detail ----
{
  const sv = { id: "P1", formatted_address: "1 Main", do_not_knock: true, contacts: [{ kind: "owner", name: "A" }], visits: [], lead_id: null };
  const next = R.reconcilePropertyDetail("property_patch", sv, { id: "P1", formatted_address: "stale", do_not_knock: false });
  assert.deepStrictEqual(next, sv, "authoritative canonical detail fully replaces optimistic copy");
  ok("Property cache update: authoritative canonical detail replaces the optimistic copy");
}

// ---- 7. Map/canvass cache update isolates the target feature ----
{
  const coll = R.reconcileCanvassFeatures("visit", { property_id: "P1", outcome: "no_answer", visited_at: "T3" }, "P1", featureColl([{ id: "P1" }, { id: "P2", last_outcome: "interested" }]));
  assert.strictEqual(feat(coll, "P1").last_outcome, "no_answer");
  assert.strictEqual(feat(coll, "P2").last_outcome, "interested", "unrelated feature untouched");
  ok("Map/canvass update patches only the matching feature, leaving others intact");
}

// ---- 9. lead acknowledgement updates lead_id (detail) + has_lead (canvass) ----
{
  const detail = R.reconcilePropertyDetail("lead_create", { id: "L5", property_id: "P1" }, { id: "P1", lead_id: null });
  assert.strictEqual(detail.lead_id, "L5");
  assert.ok(!("existing_lead_id" in detail), "legacy existing_lead_id alias is not written");
  const coll = R.reconcileCanvassFeatures("lead_create", { id: "L5", property_id: "P1" }, "P1", featureColl([{ id: "P1", has_lead: false }]));
  assert.strictEqual(feat(coll, "P1").has_lead, true);
  ok("lead ack sets Property.lead_id (Create->Open lead) and canvass has_lead=true");
}

// ---- 8 (unit). stale refresh / offline fallback safety: a non-synced or absent serverValue never mutates ----
{
  const caches = makeCaches({ "property:P1": { id: "P1", do_not_knock: true }, "section:s1:props": featureColl([{ id: "P1", do_not_knock: true }]) });
  reconcileLoop(caches, [
    { kind: "property_patch", state: "pending", body: { property_id: "P1" }, path: "/mobile/properties/P1" },  // offline, not acked
  ]);
  assert.strictEqual(caches["property:P1"].do_not_knock, true, "offline (pending) mutation never rewrites the cache");
  ok("offline/stale: a pending (unacknowledged) mutation never mutates the saved caches");
}

// ---- 10. unrelated pending mutations remain intact through reconciliation ----
{
  const caches = makeCaches({
    "property:P1": { id: "P1", visits: [] },
    "section:s1:props": featureColl([{ id: "P1" }, { id: "P2", do_not_knock: false }]),
  });
  reconcileLoop(caches, [
    { kind: "visit", state: "synced", serverValue: { id: "V1", property_id: "P1", outcome: "no_answer", visited_at: "T1" } },
    { kind: "property_patch", state: "pending", body: { property_id: "P2" } },   // unrelated, still pending
    { kind: "photo", state: "synced", serverValue: { id: "PH1" } },              // unrelated kind
  ]);
  assert.strictEqual(caches["property:P1"].visits[0].id, "V1", "acked visit reconciled");
  assert.strictEqual(feat(caches["section:s1:props"], "P2").do_not_knock, false, "unrelated pending P2 untouched");
  ok("only synced Property/Visit/Lead rows reconcile; unrelated pending + other kinds are left intact");
}

// ---- 11. reconnect convergence: optimistic values converge to the authoritative server truth ----
{
  // Rep (offline) toggled DNK ON with a guessed reason; server normalizes the reason on ack.
  const caches = makeCaches({
    "property:P1": { id: "P1", do_not_knock: true, do_not_knock_reason: "Marked by field rep" },
    "section:s1:props": featureColl([{ id: "P1", do_not_knock: true, has_lead: false }]),
  });
  const sv = { id: "P1", do_not_knock: true, do_not_knock_reason: "Homeowner request (verified)", owner_occupied: true, lead_id: "L7", visits: [{ outcome: "do_not_knock", visited_at: "T9" }] };
  reconcileLoop(caches, [{ kind: "property_patch", state: "synced", serverValue: sv }]);
  assert.strictEqual(caches["property:P1"].do_not_knock_reason, "Homeowner request (verified)", "detail converged to server reason");
  assert.strictEqual(feat(caches["section:s1:props"], "P1").has_lead, true, "canvass converged: has_lead from server lead_id");
  assert.strictEqual(feat(caches["section:s1:props"], "P1").last_outcome, "do_not_knock", "canvass last_outcome converged");
  ok("reconnect convergence: optimistic values are overwritten by authoritative server state across all caches");
}

// propertyIdForMutation resolves from serverValue / body / path deterministically.
{
  assert.strictEqual(R.propertyIdForMutation({ kind: "visit", serverValue: { property_id: "PA" } }), "PA");
  assert.strictEqual(R.propertyIdForMutation({ kind: "property_patch", path: "/mobile/properties/PB" }), "PB");
  assert.strictEqual(R.propertyIdForMutation({ kind: "lead_create", body: { property_id: "PC" } }), "PC");
  ok("propertyIdForMutation resolves the target property from server value, path, or body");
}

// ---- B3C-style conflict resolution plans (use_server / keep_local) ----
{
  const conflicted = { client_id: "property-patch:P1", kind: "property_patch", state: "conflict",
    body: { do_not_knock: true }, path: "/mobile/properties/P1",
    serverValue: { id: "P1", do_not_knock: false, do_not_knock_reason: null, visits: [], lead_id: null } };
  const useServer = R.resolveConflictPlan(conflicted, "use_server");
  assert.strictEqual(useServer.action, "use_server");
  assert.strictEqual(useServer.removeClientId, "property-patch:P1");
  assert.strictEqual(useServer.propertyId, "P1");
  assert.strictEqual(useServer.serverValue.do_not_knock, false);
  const keepLocal = R.resolveConflictPlan(conflicted, "keep_local");
  assert.strictEqual(keepLocal.action, "keep_local");
  assert.strictEqual(keepLocal.requeue.state, "pending");
  assert.strictEqual(keepLocal.requeue.attempts, 0);
  assert.deepStrictEqual(keepLocal.requeue.body, { do_not_knock: true }, "keep-local preserves the rep's body");
  assert.strictEqual(R.resolveConflictPlan({ state: "synced" }, "use_server").action, "noop", "only conflict rows resolve");
  ok("conflict resolution: use_server adopts server + drops local; keep_local re-queues the rep's body");
}

// ---- conflict DIFF preview (server vs local) ----
{
  const m = { kind: "property_patch", state: "conflict",
    body: { do_not_knock: true, do_not_knock_reason: "Rep guess" },
    serverValue: { id: "P1", do_not_knock: false, do_not_knock_reason: null, notes: "x" } };
  const rows = R.conflictDiff(m);
  const byField = Object.fromEntries(rows.map((r) => [r.field, r]));
  assert.deepStrictEqual(byField.do_not_knock, { field: "do_not_knock", label: "Do Not Knock", server: "OFF", local: "ON" });
  assert.strictEqual(byField.do_not_knock_reason.server, "—");
  assert.strictEqual(byField.do_not_knock_reason.local, "Rep guess");
  assert.ok(!("notes" in byField), "unchanged/unedited fields (notes not in body) are not shown");
  // identical values produce no diff row
  const same = R.conflictDiff({ body: { do_not_knock: true }, serverValue: { do_not_knock: true } });
  assert.strictEqual(same.length, 0, "no row when server and local agree");
  ok("conflict diff shows only edited fields that actually differ (Office vs You)");
}

// ---- diff-aware per-field merge resolution ----
{
  const m = { client_id: "property-patch:P1", kind: "property_patch", state: "conflict",
    path: "/mobile/properties/P1",
    body: { do_not_knock: true, notes: "mine notes" },
    serverValue: { id: "P1", do_not_knock: false, notes: "office notes", updated_at: "T-NEW", visits: [], lead_id: null } };
  // keep MY do_not_knock, take Office notes
  const plan = R.mergeConflictResolution(m, { do_not_knock: "mine", notes: "office" });
  assert.strictEqual(plan.action, "merge");
  assert.strictEqual(plan.removeClientId, "property-patch:P1");
  assert.deepStrictEqual(plan.optimistic, { do_not_knock: true }, "only the kept field is re-applied");
  assert.strictEqual(plan.requeue.kind, "property_patch");
  assert.strictEqual(plan.requeue.body.do_not_knock, true);
  assert.ok(!("notes" in plan.requeue.body), "Office-chosen field is not re-queued");
  assert.strictEqual(plan.requeue.body.expected_updated_at, "T-NEW", "re-queue carries the server's fresh token");
  // all Office -> no requeue (pure adopt-server)
  const allOffice = R.mergeConflictResolution(m, { do_not_knock: "office", notes: "office" });
  assert.strictEqual(allOffice.requeue, null, "all-Office choices need no re-queue");
  ok("per-field merge: keep-mine re-queued with server token, take-Office adopted, mixed choices honored");
}

console.log("\nFIELD PROPERTY/MAP CACHE SYNC: all " + n + " assertions passed");
