/*
 * RoofSpan Mobile — Field measurement EDGE IDENTITY contract (Task 4 Phase 1 closure).
 * Proves the backend's identity-preserving reconciliation is honoured by Field: an existing persisted
 * MeasurementEdge keeps ref = its server UUID through hydrate -> edit -> buildBody -> optimistic cache
 * -> offline queue serialization -> PUT, and a new local edge carries ONE stable temporary ref end to
 * end. Run: node src/tests/edge_identity.node.test.js
 */
const assert = require("assert");
const { edgeForEdit, newEdge, edgeToBody } = require("../measurementEdges");

const UUID_E1 = "11111111-1111-4111-8111-111111111111";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let passed = 0;
function ok(name, fn) { fn(); passed++; console.log("  ✓", name); }

// Mirror of Measurements.buildBody edge serialization (edges.map(edgeToBody)) + the offline path:
// buildBody() -> body cached (cacheMeasurementDetail) -> body queued (queueMutation) as JSON.
function serializeThroughQueue(edgesState) {
  const body = { edges: edgesState.map(edgeToBody) };
  // optimistic cache + AsyncStorage-backed queue both round-trip through JSON.
  const cached = JSON.parse(JSON.stringify(body));
  const queued = JSON.parse(JSON.stringify({ path: "/mobile/measurements/rev-1", body: cached }));
  return queued.body.edges;
}

ok("existing server edge hydrates with ref = MeasurementEdge UUID", () => {
  const serverEdge = { id: UUID_E1, edge_type: "eave", length_ft: 20, facet_id: "F1" };
  const edited = edgeForEdit(serverEdge);
  assert.strictEqual(edited.ref, UUID_E1, "hydrated edge must pin ref to the server UUID");
  assert.strictEqual(edited.facet_ref, "F1");
});

ok("existing edge ref survives buildBody -> optimistic cache -> queued PUT", () => {
  const edited = edgeForEdit({ id: UUID_E1, edge_type: "ridge", length_ft: 12.5 });
  // user tweaks the length in the UI, identity untouched
  const afterEdit = { ...edited, length_ft: 15 };
  const queuedEdges = serializeThroughQueue([afterEdit]);
  assert.strictEqual(queuedEdges.length, 1);
  assert.strictEqual(queuedEdges[0].ref, UUID_E1, "PUT body must still carry the original edge UUID");
  assert.strictEqual(queuedEdges[0].length_ft, 15);
  assert.ok(UUID_RE.test(queuedEdges[0].ref), "ref stays a real server UUID (never regenerated)");
});

ok("new local edge gets ONE temporary ref that survives into the queued PUT", () => {
  const fresh = newEdge();
  assert.strictEqual(fresh.ref, fresh._k, "new edge uses one key for both identity properties");
  assert.ok(!UUID_RE.test(fresh.ref), "new edge ref is a temporary (non-UUID) key -> backend INSERT");
  const tempRef = fresh.ref;
  const queuedEdges = serializeThroughQueue([fresh]);
  assert.strictEqual(queuedEdges[0].ref, tempRef, "temporary ref must survive queue serialization unchanged");
});

ok("mixed existing + new edges keep distinct, stable identities through the queue", () => {
  const existing = edgeForEdit({ id: UUID_E1, edge_type: "eave", length_ft: 20 });
  const fresh = newEdge();
  const queuedEdges = serializeThroughQueue([existing, fresh]);
  assert.strictEqual(queuedEdges[0].ref, UUID_E1);
  assert.strictEqual(queuedEdges[1].ref, fresh.ref);
  assert.notStrictEqual(queuedEdges[0].ref, queuedEdges[1].ref);
});

console.log(`FIELD EDGE IDENTITY: all ${passed} assertions passed`);
