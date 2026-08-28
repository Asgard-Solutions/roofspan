/* RoofSpan Field — roof measurement offline cache/draft contract (pure Node). */
const mc = require("../measurementCache");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

ok(mc.scopeKey({ lead_id: "l1" }) === "measurement_scope:lead:l1", "lead scope cache key is stable");
ok(mc.scopeKey({ property_id: "p1" }) === "measurement_scope:property:p1", "property scope cache key is stable");
ok(mc.detailKey("r1") === "measurement_detail:r1", "revision detail cache key is stable");
ok(mc.draftKey({ lead_id: "l1" }) === "measurement_draft:lead:l1", "unsynced draft is scoped to lead");

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

ok(mc.isLocalDraft({ local_draft: true, client_id: "x" }) === true, "local draft marker recognized");
ok(mc.isLocalDraft({ id: "server-id" }) === false, "server revision is not treated as a local draft");

if (failures) { console.error(`\nMEASUREMENT CACHE: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT CACHE: all passed");
