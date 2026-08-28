/*
 * RoofSpan Field — pure roof-measurement cache/draft helpers.
 * No React Native/device dependencies so the offline contract stays deterministic in Node tests.
 */

function _scope(scope) {
  scope = scope || {};
  if (scope.lead_id) return { kind: "lead", id: String(scope.lead_id) };
  if (scope.property_id) return { kind: "property", id: String(scope.property_id) };
  if (scope.inspection_id) return { kind: "inspection", id: String(scope.inspection_id) };
  throw new Error("measurement_scope_required");
}

function scopeKey(scope) {
  const s = _scope(scope);
  return `measurement_scope:${s.kind}:${s.id}`;
}

function detailKey(id) {
  return `measurement_detail:${id}`;
}

function draftKey(scope) {
  const s = _scope(scope);
  return `measurement_draft:${s.kind}:${s.id}`;
}

function updateMutationId(revisionId) {
  if (!revisionId) throw new Error("measurement_revision_required");
  return `measurement-update:${String(revisionId)}`;
}

function pickCurrent(list) {
  const rows = Array.isArray(list) ? list.filter(Boolean) : [];
  if (!rows.length) return null;
  return [...rows].sort((a, b) => Number(b.revision_number || 0) - Number(a.revision_number || 0))[0];
}

function makeDraft(scope, body, clientId) {
  return {
    local_draft: true,
    scope_key: scopeKey(scope),
    client_id: clientId || null,
    body: { ...(body || {}) },
    updated_at: new Date().toISOString(),
  };
}

function mergeDraft(draft, patch) {
  const base = draft || { local_draft: true, body: {} };
  return {
    ...base,
    body: { ...(base.body || {}), ...(patch || {}) },
    updated_at: new Date().toISOString(),
  };
}

function isLocalDraft(value) {
  return !!(value && value.local_draft === true && value.client_id);
}

module.exports = { scopeKey, detailKey, draftKey, updateMutationId, pickCurrent, makeDraft, mergeDraft, isLocalDraft };
