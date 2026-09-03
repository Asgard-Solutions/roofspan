// RN Navigation 7 migration regression test.
//
// Exercises the ACTUAL installed @react-navigation/routers (v7) StackRouter/TabRouter to lock in the
// navigation contract our screens depend on after the RN6 -> RN7 upgrade. The key RN7 breaking change
// is: navigate() no longer goes back to an existing screen (it pushes); { pop: true } restores the
// RN6 "return to existing screen" behavior. RoofSpan relies on this for its cross-tab shortcuts
// (Home, More "Review & update", Property -> Lead) so a duplicate screen is not stacked on top of a
// deep nested stack.
const assert = require("assert");
const { StackRouter, TabRouter } = require("@react-navigation/routers");

let passed = 0;
const ok = (m) => { passed += 1; console.log("  ok -", m); };

const NAV = (name, params, options) => ({ type: "NAVIGATE", payload: { name, params, ...(options || {}) } });
const BACK = () => ({ type: "GO_BACK" });

// Mirrors the LeadStack in mobile/App.js.
const routeNames = ["Leads", "LeadDetail", "Inspection", "Measurements", "RoofSketch"];
const opts = { routeNames, routeParamList: {}, routeGetIdList: {} };
const router = StackRouter({});

const names = (s) => s.routes.map((r) => r.name);
function deepStack() {
  // [Leads, LeadDetail(A), Inspection, Measurements]
  let s = router.getInitialState(opts);
  s = router.getStateForAction(s, NAV("LeadDetail", { id: "A" }), opts);
  s = router.getStateForAction(s, NAV("Inspection", {}), opts);
  s = router.getStateForAction(s, NAV("Measurements", {}), opts);
  return s;
}

console.log("RN7 StackRouter navigate/pop/goBack contract:");

// 1. RN7 change: navigate() WITHOUT pop does NOT go back - it pushes (even to an existing root).
{
  const s = deepStack();
  const next = router.getStateForAction(s, NAV("Leads"), opts);
  assert.strictEqual(next.routes.length, 5, "navigate() without pop should push, not pop back");
  assert.strictEqual(next.routes[next.index].name, "Leads", "focused screen is Leads");
  assert.strictEqual(next.routes[0].name, "Leads", "original root Leads still present below");
  ok("RN7: navigate() without pop pushes a new screen (documents the breaking change)");
}

// 2. Our fix: navigate(..., { pop: true }) restores RN6 behavior -> pops back to the existing root.
{
  const s = deepStack();
  const next = router.getStateForAction(s, NAV("Leads", undefined, { pop: true }), opts);
  assert.strictEqual(next.routes.length, 1, "pop:true collapses back to the existing Leads root");
  assert.deepStrictEqual(names(next), ["Leads"], "stack is just [Leads]");
  assert.strictEqual(next.index, 0, "focused index is 0");
  ok("Home 'My Leads'/'My Jobs' shortcut: pop:true returns cleanly to the list root");
}

// 3. Revisit an already-present detail with a new id (Home 'needs action' / More 'Review & update').
{
  // [Leads, LeadDetail(A), Inspection]
  let s = router.getInitialState(opts);
  s = router.getStateForAction(s, NAV("LeadDetail", { id: "A" }), opts);
  s = router.getStateForAction(s, NAV("Inspection", {}), opts);
  const next = router.getStateForAction(s, NAV("LeadDetail", { id: "B" }, { pop: true }), opts);
  assert.deepStrictEqual(names(next), ["Leads", "LeadDetail"], "pops Inspection, returns to LeadDetail");
  assert.strictEqual(next.routes[next.index].name, "LeadDetail", "focused on LeadDetail");
  assert.strictEqual(next.routes[next.index].params.id, "B", "params updated to the newly requested lead id");
  ok("Cross-tab detail revisit with pop:true reuses the existing detail screen and updates params");
}

// 4. Forward push flows that must NOT change (Measurements -> RoofSketch) and goBack returns.
{
  let s = deepStack();
  const push = router.getStateForAction(s, NAV("RoofSketch", { revision_id: "R1" }), opts);
  assert.strictEqual(push.routes[push.index].name, "RoofSketch", "RoofSketch pushed on top");
  assert.strictEqual(push.routes.length, 5, "RoofSketch is a new screen");
  const back = router.getStateForAction(push, BACK(), opts);
  assert.strictEqual(back.routes[back.index].name, "Measurements", "goBack returns to Measurements");
  assert.strictEqual(back.routes.length, 4, "goBack pops exactly one screen");
  ok("Measurements -> RoofSketch -> goBack round-trips as before (forward push unaffected)");
}

// 5. TabRouter: switching tabs works and preserves each tab's state (tab shortcuts + back behavior).
{
  const tabNames = ["Home", "LeadsTab", "Map", "JobsTab", "More"];
  const tabOpts = { routeNames: tabNames, routeParamList: {}, routeGetIdList: {} };
  const tabRouter = TabRouter({});
  let t = tabRouter.getInitialState(tabOpts);
  assert.strictEqual(t.routes[t.index].name, "Home", "starts on Home tab");
  t = tabRouter.getStateForAction(t, NAV("JobsTab"), tabOpts);
  assert.strictEqual(t.routes[t.index].name, "JobsTab", "navigate switches to JobsTab");
  t = tabRouter.getStateForAction(t, NAV("LeadsTab"), tabOpts);
  assert.strictEqual(t.routes[t.index].name, "LeadsTab", "navigate switches to LeadsTab");
  assert.strictEqual(t.routes.length, tabNames.length, "all tabs remain mounted (no tab dropped)");
  ok("TabRouter switches tabs and keeps every tab mounted");
}

console.log(`\nnavigation_v7: ${passed} assertions passed.`);
