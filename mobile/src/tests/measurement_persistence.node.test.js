"use strict";
// RoofSpan Field — measurement persistence + parity contracts (pure, Node; no RN).
// Proves the root-cause fixes: (1) newer unsynced LOCAL work is not replaced by an older server copy on
// reload; a real Office change surfaces an explicit conflict; (2) edge identity carries BOTH plane
// associations so a Field save can't erase the secondary facet link.
const assert = require("assert");
const { resolveMeasurementView } = require("../measurementReconcile");
const { edgeForEdit, edgeToBody, newEdge } = require("../measurementEdges");

let n = 0; const ok = (m) => { n++; console.log("  \u2713 " + m); };

const server = (v, area) => ({ id: "REV1", updated_at: v, facets: [{ id: "MF1", area_sqft: area }] });
const optimistic = (base, area) => ({ id: "REV1", updated_at: base, facets: [{ id: "MF1", area_sqft: area }] });
const pu = (ifMatch, state = "pending") => ({ client_id: "measurement-update:REV1", ifMatch, state });

// ---- 1. No pending local work → authoritative server copy is shown ----
{
  const v = resolveMeasurementView({ serverDetail: server("v2", 400), serverStale: false, optimistic: null, pendingUpdate: null, pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "server"); assert.strictEqual(v.status, "Synced"); assert.strictEqual(v.detail.facets[0].area_sqft, 400);
  ok("no pending local work → server copy is authoritative (Synced)");
}

// ---- 2. Offline, no pending → last cached server copy, flagged stale ----
{
  const v = resolveMeasurementView({ serverDetail: server("v2", 400), serverStale: true, optimistic: null, pendingUpdate: null, pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "server_cached"); assert.strictEqual(v.stale, true);
  ok("offline with no pending work → cached server copy shown (stale)");
}

// ---- 3. ROOT CAUSE: pending local update + server UNCHANGED → local optimistic wins (older server never replaces it) ----
{
  const v = resolveMeasurementView({ serverDetail: server("v2", 400), serverStale: false, optimistic: optimistic("v2", 999), pendingUpdate: pu("v2"), pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "local_update");
  assert.strictEqual(v.detail.facets[0].area_sqft, 999, "the newer unsynced local value is preserved, not the server's 400");
  assert.strictEqual(v.status, "Waiting to sync"); assert.strictEqual(v.conflict, false);
  const vs = resolveMeasurementView({ serverDetail: server("v2", 400), serverStale: false, optimistic: optimistic("v2", 999), pendingUpdate: pu("v2"), pendingCreate: null, isSyncing: true });
  assert.strictEqual(vs.status, "Syncing");
  ok("pending local update + unchanged server → newer LOCAL value wins on reload (Waiting to sync / Syncing)");
}

// ---- 4. Office changed the SAME revision since our base → explicit conflict (never silent overwrite) ----
{
  const v = resolveMeasurementView({ serverDetail: server("v5", 400), serverStale: false, optimistic: optimistic("v2", 999), pendingUpdate: pu("v2"), pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "conflict"); assert.strictEqual(v.status, "Needs review"); assert.strictEqual(v.conflict, true);
  assert.strictEqual(v.detail.facets[0].area_sqft, 999, "local work preserved as working copy during conflict");
  assert.strictEqual(v.serverDetail.updated_at, "v5", "office version available for explicit resolution");
  ok("pending local update + Office changed same revision → Needs review conflict (both versions preserved)");
}

// ---- 5. Conflict must NOT be inferred from a stale/offline read ----
{
  const v = resolveMeasurementView({ serverDetail: server("v5", 400), serverStale: true, optimistic: optimistic("v2", 999), pendingUpdate: pu("v2"), pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "local_update", "a stale read can't prove Office changed it → keep showing local, no false conflict");
  ok("offline stale read never fabricates a conflict; local work still wins");
}

// ---- 6. New measurement create pending → local draft is the working copy ----
{
  const draft = { local_draft: true, client_id: "c1", body: { facets: [] }, updated_at: "d1" };
  const v = resolveMeasurementView({ serverDetail: null, serverStale: false, optimistic: null, draft, pendingUpdate: null, pendingCreate: { client_id: "c1", kind: "measurement", state: "pending" }, isSyncing: false });
  assert.strictEqual(v.kind, "local_draft"); assert.strictEqual(v.status, "Waiting to sync"); assert.strictEqual(v.detail, draft);
  ok("pending new-measurement create → local draft shown until acknowledged");
}

// ---- 7. pending update but optimistic cache missing → safely falls back to server (no crash/blank) ----
{
  const v = resolveMeasurementView({ serverDetail: server("v2", 400), serverStale: false, optimistic: null, pendingUpdate: pu("v2"), pendingCreate: null, isSyncing: false });
  assert.strictEqual(v.kind, "server");
  ok("pending update with no optimistic cache falls back to the server copy");
}

// ---- 8. EDGE identity carries BOTH plane associations through hydrate → edit → body ----
{
  const srvEdge = { id: "ME1", edge_type: "valley", length_ft: 42.5, facet_id: "MF1", facet_id_secondary: "MF2", label: "V1", notes: "north" };
  const edit = edgeForEdit(srvEdge);
  assert.strictEqual(edit.ref, "ME1", "existing edge keeps its server id as ref (identity preserved)");
  assert.strictEqual(edit.facet_ref, "MF1"); assert.strictEqual(edit.facet_ref_secondary, "MF2");
  assert.strictEqual(edit.ft, "42"); assert.strictEqual(edit.in, "6");   // 42.5 ft → 42 ft 6 in (no manual decimal conversion)
  const body = edgeToBody(edit, 0);
  assert.strictEqual(body.ref, "ME1"); assert.strictEqual(body.facet_ref, "MF1");
  assert.strictEqual(body.facet_ref_secondary, "MF2", "secondary plane association preserved (not erased)");
  assert.strictEqual(body.label, "V1"); assert.strictEqual(body.length_ft, 42.5);
  ok("edge round-trip preserves identity + BOTH facet associations + label + ft/in conversion");
}

// ---- 9. a brand-new edge carries empty associations (nothing to preserve) ----
{
  const b = edgeToBody(newEdge(), 1);
  assert.strictEqual(b.facet_ref, null); assert.strictEqual(b.facet_ref_secondary, null);
  ok("new edge serializes with null associations");
}

console.log("\nFIELD MEASUREMENT PERSISTENCE + PARITY: all " + n + " assertions passed");
