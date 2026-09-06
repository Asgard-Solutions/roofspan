"use strict";
const assert = require("assert");
const Q = require("../queue");
const M = require("../measurementReconcile");
const R = require("../measurementRecovery");

function clone(v) { return JSON.parse(JSON.stringify(v)); }
function detail() {
  return {
    id: "R1", updated_at: "2026-09-06T10:00:00Z", source: "office",
    provider: "provider-a", report_id: "report-a", reported_area_sqft: 1000, notes: "base notes",
    structures: [{ id: "S1", name: "House", structure_type: "main_house", included_in_scope: true, sort: 0 }],
    facets: [{ id: "F1", structure_id: "S1", facet_label: "F1", pitch_rise: 6, area_sqft: 100, sort: 0 }],
    edges: [{ id: "E1", facet_id: "F1", edge_type: "ridge", length_ft: 40, sort: 0 }],
    penetrations: [{ id: "P1", facet_id: "F1", pen_type: "pipe_boot", quantity: 1, sort: 0 }],
    summary: { existing_layers: 1 },
  };
}

(function authoritative_output_is_normalized_to_identity_preserving_write_shape() {
  const body = M.measurementDocumentFromRevision(detail());
  assert.strictEqual(body.source, "office");
  assert.strictEqual(body.structures[0].ref, "S1");
  assert.strictEqual(body.structures[0].id, undefined);
  assert.strictEqual(body.facets[0].ref, "F1");
  assert.strictEqual(body.facets[0].structure_ref, "S1");
  assert.strictEqual(body.facets[0].structure_id, undefined);
  assert.strictEqual(body.edges[0].ref, "E1");
  assert.strictEqual(body.edges[0].facet_ref, "F1");
  assert.strictEqual(body.edges[0].facet_id, undefined);
  assert.strictEqual(body.penetrations[0].ref, "P1");
  assert.strictEqual(body.penetrations[0].facet_ref, "F1");
  assert.strictEqual(body.penetrations[0].facet_id, undefined);
})();

(function durable_row_survives_working_draft_clear_and_merges_disjoint_changes() {
  const baseDetail = detail();
  const baseBody = M.measurementDocumentFromRevision(baseDetail);
  const fieldBody = { ...clone(baseBody), lead_id: "L1", mark_field_complete: false };
  fieldBody.edges[0].length_ft = 45;
  const mutation = Q.makeMutation({
    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",
    body: fieldBody, ifMatch: baseDetail.updated_at, baseBody, baseToken: baseDetail.updated_at,
  });
  assert.deepStrictEqual(mutation.base_body, baseBody);
  assert.strictEqual(mutation.base_token, baseDetail.updated_at);

  const office = clone(baseDetail);
  office.updated_at = "2026-09-06T10:05:00Z";
  office.source = "import";
  office.facets[0].area_sqft = 110;
  office.facets.push({
    id: "F2", structure_id: "S1", facet_label: "F2", pitch_rise: 8, area_sqft: 75, sort: 1,
  });
  office.notes = "Office-only note";
  const inputs = M.measurementConflictMergeInputs({ ...mutation, state: "conflict" }, office);
  assert.strictEqual(inputs.ok, true);
  assert.strictEqual(inputs.office.facets[0].ref, "F1");
  assert.strictEqual(inputs.office.facets[0].structure_ref, "S1");
  assert.strictEqual(inputs.office.facets[1].ref, "F2");
  const merged = R.threeWayMergeMeasurement(inputs.base, inputs.field, inputs.office);
  assert.strictEqual(merged.clean, true);
  const next = M.buildMergedMeasurementBody(mutation.body, merged.merged);
  assert.strictEqual(next.facets.length, 2, "Office-only plane addition must survive");
  assert.strictEqual(next.facets[0].area_sqft, 110, "Office-only plane change must survive");
  assert.strictEqual(next.facets[0].ref, "F1", "existing plane UUID must be sent as ref");
  assert.strictEqual(next.facets[0].structure_ref, "S1", "plane relationship must stay linked");
  assert.strictEqual(next.facets[1].ref, "F2", "Office-added plane UUID must be retained");
  assert.strictEqual(next.edges[0].length_ft, 45, "Field-only roof-line change must survive");
  assert.strictEqual(next.edges[0].ref, "E1", "existing line UUID must be sent as ref");
  assert.strictEqual(next.edges[0].facet_ref, "F1", "line-to-plane relationship must stay linked");
  assert.strictEqual(next.source, "import", "Office-only source change must survive");
  assert.strictEqual(next.notes, "Office-only note", "Office-only hidden metadata must survive");
  assert.strictEqual(next.lead_id, "L1", "routing scope remains from the Field mutation");
})();

(function repeated_local_save_keeps_the_original_pending_base() {
  const base = detail();
  const original = M.measurementDocumentFromRevision(base);
  const pending = Q.makeMutation({
    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1", body: original,
    ifMatch: base.updated_at, baseBody: original, baseToken: base.updated_at,
  });
  const optimistic = clone(base);
  optimistic.updated_at = base.updated_at;
  optimistic.facets[0].area_sqft = 999;
  const chosen = M.chooseDurableMeasurementBase(optimistic, pending);
  assert.strictEqual(chosen.ok, true);
  assert.deepStrictEqual(chosen.baseBody, original);
  assert.strictEqual(chosen.baseToken, base.updated_at);
})();

(function legacy_or_mismatched_rows_cannot_blindly_keep_mine() {
  const base = detail();
  const body = M.measurementDocumentFromRevision(base);
  const legacy = Q.makeMutation({
    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",
    body, ifMatch: base.updated_at,
  });
  assert.strictEqual(M.measurementConflictMergeInputs({ ...legacy, state: "conflict" }, base).ok, false);
  assert.strictEqual(M.chooseDurableMeasurementBase(base, legacy).ok, false);

  const mismatch = { ...legacy, base_body: body, base_token: "older-token" };
  const result = M.measurementConflictMergeInputs(mismatch, base);
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, "base_token_mismatch");
})();

(function pre_normalization_durable_rows_are_healed_when_read() {
  const rawServerShape = detail();
  const pending = Q.makeMutation({
    kind: "measurement_update", method: "put", path: "/mobile/measurements/R1",
    body: M.measurementDocumentFromRevision(rawServerShape), ifMatch: rawServerShape.updated_at,
    baseBody: rawServerShape, baseToken: rawServerShape.updated_at,
  });
  const chosen = M.chooseDurableMeasurementBase(rawServerShape, pending);
  assert.strictEqual(chosen.ok, true);
  assert.strictEqual(chosen.baseBody.structures[0].ref, "S1");
  assert.strictEqual(chosen.baseBody.facets[0].structure_ref, "S1");
})();

(function superseded_create_conversion_uses_the_acknowledged_server_as_its_new_base() {
  const server = detail();
  server.updated_at = "2026-09-06T10:10:00Z";
  const newerCreate = Q.makeMutation({ kind: "measurement", method: "post", path: "/mobile/measurements", body: { lead_id: "L1", structures: [] } });
  const converted = M.buildConvertedUpdateMutation(newerCreate, "R1", server.updated_at, server);
  assert.strictEqual(converted.kind, "measurement_update");
  assert.strictEqual(converted.base_token, server.updated_at);
  assert.deepStrictEqual(converted.base_body, M.measurementDocumentFromRevision(server));
  assert.deepStrictEqual(converted.body, newerCreate.body);
})();

console.log("measurement durable merge-base tests passed");
