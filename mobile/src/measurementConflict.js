"use strict";
/* Pure decision layer for atomic Field measurement Use-Office resolution. */
const K = require("./measurementCache");
const { measScopeFromBody } = require("./measurementReconcile");

const RESOLVABLE_STATES = new Set(["pending", "conflict", "failed"]);
function clone(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function revisionIdFromClientId(clientId) {
  const value = String(clientId || "");
  return value.startsWith("measurement-update:") ? value.slice("measurement-update:".length) : null;
}
function isFullOfficeRevision(value, expectedRevisionId = null) {
  if (!value || typeof value !== "object") return false;
  const id = value.id == null ? null : String(value.id);
  if (!id || (expectedRevisionId != null && id !== String(expectedRevisionId))) return false;
  if (value.updated_at == null || value.updated_at === "") return false;
  for (const key of ["structures", "facets", "edges", "penetrations"]) {
    if (!Object.prototype.hasOwnProperty.call(value, key) || !Array.isArray(value[key])) return false;
  }
  if (!Object.prototype.hasOwnProperty.call(value, "summary")) return false;
  if (value.summary !== null && (typeof value.summary !== "object" || Array.isArray(value.summary))) return false;
  return true;
}
function measurementListItemFromDetail(detail) {
  const totals = detail && detail.totals && typeof detail.totals === "object" ? detail.totals : {};
  const rawArea = Number(totals.total_area_sqft);
  const area = Number.isFinite(rawArea) ? rawArea : 0;
  const rawSquares = Number(totals.total_squares);
  return {
    id: String(detail.id), set_id: detail.set_id == null ? null : String(detail.set_id),
    revision_number: detail.revision_number, status: detail.status, source: detail.source,
    is_immutable: !!detail.is_immutable, total_area_sqft: area,
    total_squares: Number.isFinite(rawSquares) ? rawSquares : Math.round((area / 100) * 100) / 100,
    created_by: detail.created_by == null ? null : detail.created_by,
    created_at: detail.created_at == null ? null : detail.created_at,
    verified_at: detail.verified_at == null ? null : detail.verified_at,
    supersedes_revision_id: detail.supersedes_revision_id == null ? null : String(detail.supersedes_revision_id),
  };
}
function replaceRevisionInList(list, detail) {
  const rows = Array.isArray(list) ? list.filter(Boolean) : [];
  const item = measurementListItemFromDetail(detail);
  let found = false;
  const next = rows.map((row) => {
    if (row && String(row.id) === item.id) { found = true; return item; }
    return row;
  });
  if (!found) next.push(item);
  return next;
}
function buildMeasurementUseOfficeReview(mutation, scope, serverDetail) {
  if (!mutation || mutation.kind !== "measurement_update") return { ok: false, reason: "not_measurement_update" };
  if (!RESOLVABLE_STATES.has(mutation.state)) return { ok: false, reason: "mutation_not_resolvable" };
  const revisionId = revisionIdFromClientId(mutation.client_id);
  if (!revisionId) return { ok: false, reason: "revision_missing" };
  const generation = Number(mutation.mutation_generation == null ? 1 : mutation.mutation_generation);
  if (!Number.isFinite(generation) || generation < 1) return { ok: false, reason: "generation_invalid" };
  if (!isFullOfficeRevision(serverDetail, revisionId)) return { ok: false, reason: "office_revision_incomplete" };
  let listKey;
  try {
    listKey = K.scopeKey(scope);
    const mutationScope = measScopeFromBody(mutation.body);
    if (!mutationScope || K.scopeKey(mutationScope) !== listKey) return { ok: false, reason: "scope_mismatch" };
  } catch (e) {
    return { ok: false, reason: "scope_missing" };
  }
  return {
    ok: true,
    reviewed: {
      clientId: String(mutation.client_id), revisionId,
      mutationGeneration: generation, expectedState: mutation.state,
      detailKey: K.detailKey(revisionId), draftKey: K.draftKey(scope),
      workingKey: K.workingKey(scope), listKey,
      serverDetail: clone(serverDetail),
    },
  };
}
function stale(reason) {
  const error = new Error(reason);
  error.__stale = reason;
  throw error;
}
function validateLiveMutation(reviewed, live) {
  if (!live) stale("mutation_missing");
  if (String(live.client_id || "") !== reviewed.clientId) stale("mutation_client_changed");
  if (live.kind !== "measurement_update") stale("mutation_kind_changed");
  if (revisionIdFromClientId(live.client_id) !== reviewed.revisionId) stale("mutation_revision_changed");
  if (Number(live.mutation_generation == null ? 1 : live.mutation_generation) !== Number(reviewed.mutationGeneration)) {
    stale("mutation_generation_changed");
  }
  if (live.state !== reviewed.expectedState) stale("mutation_state_changed");
  try {
    const liveScope = measScopeFromBody(live.body);
    if (!liveScope || K.scopeKey(liveScope) !== reviewed.listKey) stale("mutation_scope_changed");
  } catch (e) {
    if (e && e.__stale) throw e;
    stale("mutation_scope_changed");
  }
}
async function applyMeasurementResolutionInTx(tx, reviewed) {
  if (!tx || !reviewed || !isFullOfficeRevision(reviewed.serverDetail, reviewed.revisionId)) {
    throw new Error("invalid_measurement_resolution");
  }
  const live = await tx.readMutation(reviewed.clientId);
  validateLiveMutation(reviewed, live);
  const removed = await tx.deleteMutation(
    reviewed.clientId, reviewed.mutationGeneration, reviewed.expectedState,
  );
  if (removed !== 1) stale("mutation_guard_missed");

  const currentList = await tx.readCache(reviewed.listKey);
  await tx.writeCache(reviewed.detailKey, reviewed.serverDetail);
  await tx.writeCache(reviewed.draftKey, null);
  await tx.writeCache(reviewed.workingKey, null);
  await tx.writeCache(reviewed.listKey, replaceRevisionInList(currentList, reviewed.serverDetail));
  return { action: "use_office", revisionId: reviewed.revisionId, serverDetail: clone(reviewed.serverDetail) };
}

module.exports = {
  revisionIdFromClientId,
  isFullOfficeRevision,
  measurementListItemFromDetail,
  replaceRevisionInList,
  buildMeasurementUseOfficeReview,
  validateLiveMutation,
  applyMeasurementResolutionInTx,
};
