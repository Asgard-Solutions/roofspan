/* RoofSpan Field — roof measurement offline cache/draft contract (pure Node). */
const mc = require("../measurementCache");
const queue = require("../queue");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

ok(mc.scopeKey({ lead_id: "l1" }) === "measurement_scope:lead:l1", "lead scope cache key is stable");
ok(mc.scopeKey({ property_id: "p1" }) === "measurement_scope:property:p1", "property scope cache key is stable");
ok(mc.detailKey("r1") === "measurement_detail:r1", "revision detail cache key is stable");
ok(mc.draftKey({ lead_id: "l1" }) === "measurement_draft:lead:l1", "unsynced draft is scoped to lead");
ok(mc.updateMutationId("r1") === "measurement-update:r1", "existing revision updates use one deterministic queue identity");

const list = [{ id: "r1", revision_number: 1 }, { id: "r2", revision_number: 2 }];
ok(mc.pickCurrent(list).id === "r2", "highest revision is selected regardless of API ordering");
ok(mc.pickCurrent([]) === null, "empty revision list has no current measurement");

const draft = mc.makeDraft({ lead_id: "l1" }, { structures: [{ ref: "s1" }], facets: [] }, "client-123");
ok(draft.scope_key === "measurement_scope:lead:l1", "draft records its measurement scope");
ok(draft.client_id === "client-123", "draft preserves queue client id for mutation upsert");
ok(draft.body.structures.length === 1, "draft preserves the editable whole-document body");

const next = mc.mergeDraft(draft, { facets: [{ ref: "f1", area_sqft: 100 }] });
ok(next.client_id === "client-123", "editing a draft keeps the same queued create mutation identity");
ok(next.body.structures.length === 1 && next.body.facets.length === 1, "draft edits merge without losing prior measurement sections");

const mutation = queue.makeMutation({ kind: "measurement", method: "post", path: "/mobile/measurements", clientId: "client-123" });
ok(mutation.client_id === "client-123" && mutation.idempotency_key === "client-123", "measurement draft can reuse one durable queue/idempotency identity");

const firstUpdate = queue.makeMutation({ kind: "measurement_update", method: "put", path: "/mobile/measurements/r1", ifMatch: "server-v1", body: { notes: "first" } });
const secondUpdate = queue.makeMutation({ kind: "measurement_update", method: "put", path: "/mobile/measurements/r1", ifMatch: "server-v1", body: { notes: "latest" } });
ok(firstUpdate.client_id === mc.updateMutationId("r1"), "measurement update queue derives the revision-stable identity automatically");
ok(firstUpdate.client_id === secondUpdate.client_id, "repeated offline edits to one server revision replace the same queued PUT");
ok(secondUpdate.body.notes === "latest", "the coalesced queued update keeps the latest whole-document payload");

ok(mc.isLocalDraft({ local_draft: true, client_id: "x" }) === true, "local draft marker recognized");
ok(mc.isLocalDraft({ id: "server-id" }) === false, "server revision is not treated as a local draft");

if (failures) { console.error(`\nMEASUREMENT CACHE: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT CACHE: all passed");
