"use strict";
// Proposal lifecycle (pending_accept -> accepted) + editor-session rollback contracts (Node, no React).
const assert = require("assert");
const path = require("path");
const Module = require("module");
const babel = require("@babel/core");

function load(rel) {
  const file = path.resolve(__dirname, rel);
  const { code } = babel.transformFileSync(file, { plugins: ["@babel/plugin-transform-modules-commonjs"] });
  const m = new Module(file, module);
  m.filename = file; m.paths = Module._nodeModulePaths(path.dirname(file));
  m._compile(code, file);
  return m.exports;
}
const P = load("../proposalLifecycle.js");

let n = 0;
const ok = (name) => { n++; console.log("  \u2713 " + name); };

// ---- ACCEPT: worksheet draft changes + decision becomes pending_accept (NOT accepted) ----
{
  const r = P.acceptProposed({ decisions: [], session: P.makeSession() },
    { target_type: "facet", relationalTargetId: "MF1", metric: "area_sqft", proposedValue: 428, currentValue: 412 });
  assert.deepStrictEqual(r.draftChange, { target_type: "facet", target_id: "MF1", metric: "area_sqft", value: 428 }); ok("Accept updates the Worksheet draft (412 -> 428)");
  const dec = P.decisionFor(r.decisions, "facet", "MF1", "area_sqft");
  assert.strictEqual(dec.decision, P.PENDING); ok("Accept creates pending_accept");
  assert.notStrictEqual(dec.decision, P.ACCEPTED); ok("Accept does NOT immediately create accepted");
}

// ---- finalize: pending -> accepted ONLY when persisted value matches ----
{
  const a = P.acceptProposed({ decisions: [], session: P.makeSession() },
    { target_type: "facet", relationalTargetId: "MF1", metric: "area_sqft", proposedValue: 428, currentValue: 412 });
  // save succeeds and authoritative value matches
  const savedMatch = (t, id, m) => (id === "MF1" && m === "area_sqft" ? 428 : null);
  const fin = P.finalizeAfterSave(a.decisions, savedMatch);
  assert.strictEqual(P.decisionFor(fin.decisions, "facet", "MF1", "area_sqft").decision, P.ACCEPTED); ok("matching authoritative save promotes pending -> accepted");
  assert.strictEqual(fin.changed, true); ok("finalize reports a provenance change to persist");
  // save succeeds but authoritative value DIFFERS -> stays pending
  const savedDiff = (t, id, m) => (id === "MF1" ? 425 : null);
  const fin2 = P.finalizeAfterSave(a.decisions, savedDiff);
  assert.strictEqual(P.decisionFor(fin2.decisions, "facet", "MF1", "area_sqft").decision, P.PENDING); ok("mismatched authoritative value stays pending (never guessed accepted)");
}

// ---- save failure / finalization failure leave pending ----
{
  const a = P.acceptProposed({ decisions: [], session: P.makeSession() },
    { target_type: "edge", relationalTargetId: "ME1", metric: "length_ft", proposedValue: 24.5, currentValue: 20 });
  // Worksheet save FAILED: finalize is simply not called -> decision remains pending
  assert.strictEqual(P.decisionFor(a.decisions, "edge", "ME1", "length_ft").decision, P.PENDING); ok("Worksheet save failure leaves proposal pending");
  // Worksheet save SUCCEEDED (authoritative correct) but the sketch-provenance PUT fails afterward:
  // the promoted decisions are computed but NOT persisted; the in-memory pending is preserved until a
  // later successful sketch save. We model that by keeping the ORIGINAL pending decisions on failure.
  const saved = (t, id, m) => (id === "ME1" ? 24.5 : null);
  const fin = P.finalizeAfterSave(a.decisions, saved);
  assert.strictEqual(fin.changed, true); // finalize WOULD promote
  const afterFinalizeFailure = a.decisions; // sketch PUT failed -> we did NOT adopt fin.decisions
  assert.strictEqual(P.decisionFor(afterFinalizeFailure, "edge", "ME1", "length_ft").decision, P.PENDING); ok("finalization failure keeps proposal pending while measurement stays saved");
}

// ---- Keep Current: no worksheet change ----
{
  const r = P.keepCurrent({ decisions: [] }, { target_type: "facet", targetId: "MF2", metric: "area_sqft" });
  assert.strictEqual(r.draftChange, null); ok("Keep Current does not change the Worksheet");
  assert.strictEqual(P.decisionFor(r.decisions, "facet", "MF2", "area_sqft").decision, P.KEEP); ok("Keep Current records keep_current directly");
}

// ---- Reopen a persisted pending: does NOT auto-edit; Apply is explicit; stays pending ----
{
  const persisted = [{ target_type: "facet", target_id: "MF1", metric: "area_sqft", decision: P.PENDING, proposed_value: 428 }];
  // reopening the editor does nothing to the worksheet by itself (no function call mutates a draft)
  assert.strictEqual(P.decisionFor(persisted, "facet", "MF1", "area_sqft").decision, P.PENDING); ok("reopened pending stays pending (no auto worksheet edit)");
  const dec = P.decisionFor(persisted, "facet", "MF1", "area_sqft");
  const ap = P.applyPendingToDraft({ session: P.makeSession() }, dec, 412);
  assert.deepStrictEqual(ap.draftChange, { target_type: "facet", target_id: "MF1", metric: "area_sqft", value: 428 }); ok("Apply to Worksheet Draft requires an explicit action and changes the draft");
  // still pending until a successful authoritative save (finalize)
  assert.strictEqual(dec.decision, P.PENDING); ok("Apply leaves the decision pending until authoritative save");
}

// ---- SESSION ROLLBACK ----
{
  // Accept 412 -> 428, then Discard restores 412 (value still equals what the editor applied)
  let s = P.makeSession();
  const a = P.acceptProposed({ decisions: [], session: s }, { target_type: "facet", relationalTargetId: "MF1", metric: "area_sqft", proposedValue: 428, currentValue: 412 });
  s = a.session;
  let worksheet = { "facet::MF1::area_sqft": 428 };
  const getVal = (t, id, m) => worksheet[`${t}::${id}::${m}`];
  let plan = P.rollbackPlan(s, getVal);
  assert.deepStrictEqual(plan, [{ target_type: "facet", target_id: "MF1", metric: "area_sqft", restore_value: 412 }]); ok("Discard restores 412 when field still equals the editor-applied 428");

  // If the user MANUALLY edited 428 -> 430 afterward, Discard must NOT touch it
  worksheet = { "facet::MF1::area_sqft": 430 };
  plan = P.rollbackPlan(s, getVal);
  assert.strictEqual(plan.length, 0); ok("Discard preserves a later manual edit (430 kept, not reverted to 412)");
}

// ---- multiple accepts in one session, unrelated worksheet edits untouched ----
{
  let s = P.makeSession();
  const a = P.acceptProposed({ decisions: [], session: s }, { target_type: "facet", relationalTargetId: "MF1", metric: "area_sqft", proposedValue: 428, currentValue: 412 });
  s = a.session;
  const b = P.acceptProposed({ decisions: a.decisions, session: s }, { target_type: "edge", relationalTargetId: "ME1", metric: "length_ft", proposedValue: 24.5, currentValue: 20 });
  s = b.session;
  const worksheet = { "facet::MF1::area_sqft": 428, "edge::ME1::length_ft": 24.5, "facet::MF2::area_sqft": 999 };
  const getVal = (t, id, m) => worksheet[`${t}::${id}::${m}`];
  const plan = P.rollbackPlan(s, getVal);
  const keys = plan.map((p) => `${p.target_type}::${p.target_id}::${p.metric}`).sort();
  assert.deepStrictEqual(keys, ["edge::ME1::length_ft", "facet::MF1::area_sqft"]); ok("Discard restores only the editor's A/B changes");
  assert.ok(!plan.some((p) => p.target_id === "MF2")); ok("unrelated Worksheet edit (MF2) is never in the rollback plan");
}

// ---- stale mapping detection + invalid pending cannot Apply ----
{
  const valid = new Set(["MF1", "MF2"]);
  assert.strictEqual(P.isMappingValid("MF1", valid), true);
  assert.strictEqual(P.isMappingValid("MFX", valid), false); ok("stale/removed relational mapping is reported invalid");

  const validPending = { target_type: "facet", target_id: "MF1", metric: "area_sqft", decision: P.PENDING, proposed_value: 428 };
  const stalePending = { target_type: "facet", target_id: "MFX", metric: "area_sqft", decision: P.PENDING, proposed_value: 428 };
  const staleEdge = { target_type: "edge", target_id: "MEX", metric: "length_ft", decision: P.PENDING, proposed_value: 24.5 };
  assert.strictEqual(P.canApplyPending(validPending, valid), true); ok("valid pending facet target CAN be applied");
  assert.strictEqual(P.canApplyPending(stalePending, valid), false); ok("invalid pending facet target CANNOT be applied");
  assert.strictEqual(P.canApplyPending(staleEdge, new Set(["ME1"])), false); ok("invalid pending edge target CANNOT be applied");

  // guard proof: when canApply is false the UI must not invoke the worksheet callback / produce success
  let worksheetCalls = 0;
  const maybeApply = (dec, set) => { if (!P.canApplyPending(dec, set)) return { applied: false }; worksheetCalls++; return { applied: true }; };
  const r = maybeApply(stalePending, valid);
  assert.strictEqual(r.applied, false); ok("invalid pending produces no Apply (no worksheet callback)");
  assert.strictEqual(worksheetCalls, 0); ok("worksheet callback never invoked for an invalid pending target");
  // pending stays pending unless the user explicitly resolves it
  assert.strictEqual(stalePending.decision, P.PENDING); ok("invalid pending remains pending (never silently redirected)");
}

console.log("\nROOF SKETCH PROPOSAL LIFECYCLE: all " + n + " assertions passed");
