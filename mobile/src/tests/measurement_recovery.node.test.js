/* RoofSpan Field — one-time measurement startup RECOVERY decisions (pure Node). */
const rec = require("../measurementRecovery");

let failures = 0;
function ok(cond, msg) {
  if (cond) console.log("  \u2713", msg);
  else { console.error("  \u2717 FAIL:", msg); failures++; }
}

// A working draft carries its base pointer (id + if_match) plus edit-shape content.
const baseWd = () => ({
  working: true,
  base: { id: "REV1", if_match: "t1" },
  structures: [{ ref: "s1", name: "Main", structure_type: "main_house", included_in_scope: true }],
  facets: [{ ref: "f1", facet_label: "F1", pitch_rise: 6, area_sqft: 800, width_ft: 40, length_ft: 20 }],
  edges: [{ edge_type: "eave", length_ft: 40 }],
  pens: [{ pen_type: "pipe_boot", quantity: 2 }, { pen_type: "skylight", quantity: 0 }],
  summary: { existing_covering_type: "shingle" },
});
const serverRev = () => ({
  id: "REV1", updated_at: "t1",
  structures: [{ id: "MS1", name: "Main", structure_type: "main_house", included_in_scope: true }],
  facets: [{ id: "MF1", facet_label: "F1", pitch_rise: 6, area_sqft: 800, width_ft: 40, length_ft: 20 }],
  edges: [{ id: "ME1", edge_type: "eave", length_ft: 40 }],
  penetrations: [{ id: "MP1", pen_type: "pipe_boot", quantity: 2 }],
  summary: { existing_covering_type: "shingle" },
});

// ---------------- canonical compare across edit-shape vs server-detail shape ----------------
ok(rec.canonicalEqual(baseWd(), serverRev()) === true, "canonicalEqual matches equivalent content across edit vs server shapes (zero-qty pens ignored)");
const changed = serverRev(); changed.facets[0].area_sqft = 999;
ok(rec.canonicalEqual(baseWd(), changed) === false, "canonicalEqual detects a real content difference");

// ---------------- working key + client_id parsers ----------------
ok(JSON.stringify(rec.parseWorkingScope("measurement_working:measurement_scope:lead:L9")) === JSON.stringify({ lead_id: "L9" }), "parses lead scope from the working key");
ok(rec.parseWorkingScope("measurement_working:measurement_scope:property:P3").property_id === "P3", "parses property scope from the working key");
ok(rec.parseUpdateRevisionId("measurement-update:REV5") === "REV5", "parses revision id from an update client_id");
ok(rec.parseUpdateRevisionId("measurement:abc") === null, "create client_id has no update revision id");

// ---------------- classifyOrphanWorkingDraft (never silently delete) ----------------
const emptyWd = { working: true, base: { id: "REV1", if_match: "t1" }, structures: [], facets: [], edges: [], pens: [], summary: {} };
ok(rec.classifyOrphanWorkingDraft({ wd: emptyWd, hasActiveMutation: false, baseRevision: serverRev() }).action === "clear", "empty orphaned working draft → clear (nothing to lose)");
ok(rec.classifyOrphanWorkingDraft({ wd: baseWd(), hasActiveMutation: true, baseRevision: serverRev() }).action === "keep", "an ACTIVE mutation → keep (not orphaned, still in flight)");
ok(rec.classifyOrphanWorkingDraft({ wd: baseWd(), hasActiveMutation: false, baseRevision: serverRev() }).action === "clear", "content identical to its recorded base → clear (mirrors Office, no real edit)");

const advancedBase = serverRev(); advancedBase.updated_at = "t2"; advancedBase.facets[0].area_sqft = 950;
const edited = baseWd(); edited.facets[0].area_sqft = 900;
const conflictDecision = rec.classifyOrphanWorkingDraft({ wd: edited, hasActiveMutation: false, baseRevision: advancedBase });
ok(conflictDecision.action === "conflict" && conflictDecision.serverDetail === advancedBase, "differs AND Office advanced past base → conflict (preserve + explicit resolution)");

const editedNoAdvance = baseWd(); editedNoAdvance.facets[0].area_sqft = 900; // base still t1 == serverRev.updated_at
ok(rec.classifyOrphanWorkingDraft({ wd: editedNoAdvance, hasActiveMutation: false, baseRevision: serverRev() }).action === "keep", "differs but Office NOT advanced → keep (never delete unsynced work)");
ok(rec.classifyOrphanWorkingDraft({ wd: baseWd(), hasActiveMutation: false, baseRevision: null }).action === "keep", "content present but base unknown → keep (never delete on an uncertain compare)");

// ---------------- recoveryAttentionItem (route failed + conflict; ignore the rest) ----------------
const conf = rec.recoveryAttentionItem({ state: "conflict", kind: "measurement_update", client_id: "measurement-update:REV1", body: { lead_id: "L1" }, error: "changed on server" });
ok(conf && conf.kind === "conflict" && conf.revisionId === "REV1" && conf.scope.lead_id === "L1", "conflict update → attention item with revision id + lead scope");
const fail = rec.recoveryAttentionItem({ state: "failed", kind: "measurement", client_id: "c-uuid", serverValue: null, body: { property_id: "P1" }, error: "HTTP 422" });
ok(fail && fail.kind === "failed" && fail.scope.property_id === "P1" && fail.error === "HTTP 422", "failed create → attention item with property scope + reason");
ok(rec.recoveryAttentionItem({ state: "pending", kind: "measurement_update", body: {} }) === null, "pending mutation is not an attention item");
ok(rec.recoveryAttentionItem({ state: "synced", kind: "measurement", body: {} }) === null, "synced mutation is not an attention item");

if (failures) { console.error(`\nMEASUREMENT RECOVERY: ${failures} failure(s)`); process.exit(1); }
console.log("\nMEASUREMENT RECOVERY: all passed");
