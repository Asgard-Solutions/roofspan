"use strict";
/*
 * RoofSpan Field — measurement view reconciliation + acknowledgement lifecycle (pure, Node-testable; no RN).
 *
 * ROOT CAUSE this fixes: the sync engine had NO measurement acknowledgement lifecycle (unlike the sketch
 * ack lifecycle). When a `measurement` create or `measurement_update` was acknowledged, the authoritative
 * server revision was never written into the detail/list caches, the durable local draft was never retired,
 * and the open screen was never notified — so the field only converged via a later 15s poll (and a `failed`
 * mutation was mis-shown as merely "waiting"). This module supplies the PURE decision layer consumed by the
 * serialized storage boundary in sync.js (`_reconcileMeasurementAcks`), mirroring roofSketchAck.js.
 *
 * Rule enforced here: the newest DURABLE LOCAL unsynced measurement is the working copy until Office
 * acknowledges it, the user discards it, or Office changed the SAME revision (a real conflict that must be
 * resolved explicitly). A late acknowledgement must NEVER delete a newer local edit.
 */

const { workingDraftHasContent } = require("./measurementDraftPriority");

// Canonical, salesperson-facing statuses for the explicit measurement mutation state table.
const STATUS = {
  synced: "Synced",
  waiting: "Waiting to sync",
  syncing: "Syncing",
  failed: "Sync failed — retry needed",
  conflict: "Conflict — review required",
  locked: "Locked — new revision needed",
  savedLocal: "Saved on device",
};

// Explicit state table: map ONE durable mutation to the truthful field behavior. A failed mutation is
// NEVER represented as merely waiting; a conflict is preserved for review; a locked revision points at the
// supported new-revision path.
function measurementSyncState(mutation, isSyncing) {
  if (!mutation) return { state: "none", status: STATUS.synced, tone: "ok", conflict: false, locked: false, failed: false, reason: null };
  switch (mutation.state) {
    case "pending":
      return { state: "pending", status: isSyncing ? STATUS.syncing : STATUS.waiting, tone: "pending", conflict: false, locked: false, failed: false, reason: null };
    case "synced":
      return { state: "synced", status: STATUS.synced, tone: "ok", conflict: false, locked: false, failed: false, reason: null };
    case "failed":
      return { state: "failed", status: STATUS.failed, tone: "warn", conflict: false, locked: false, failed: true, reason: mutation.error || "Sync failed — retry needed" };
    case "conflict":
      return { state: "conflict", status: STATUS.conflict, tone: "warn", conflict: true, locked: false, failed: false, reason: mutation.error || null };
    case "locked":
      return { state: "locked", status: STATUS.locked, tone: "warn", conflict: false, locked: true, failed: false, reason: mutation.error || null };
    default:
      return { state: mutation.state, status: STATUS.waiting, tone: "pending", conflict: false, locked: false, failed: false, reason: null };
  }
}

// Insert-or-update the acknowledged revision into the scoped measurement-list cache (keyed by id).
// Preserves every other cached revision; never drops the list.
function upsertRevision(list, rev) {
  if (!rev || rev.id == null) return Array.isArray(list) ? list : [];
  const rows = Array.isArray(list) ? list.filter(Boolean) : [];
  const id = String(rev.id);
  let found = false;
  const next = rows.map((r) => {
    if (r && String(r.id) === id) { found = true; return { ...r, ...rev }; }
    return r;
  });
  if (!found) next.push(rev);
  return next;
}

// The measurement scope (lead/property/inspection) lives inside the mutation body (buildBody spreads scope).
function measScopeFromBody(body) {
  if (!body) return null;
  if (body.lead_id) return { lead_id: body.lead_id };
  if (body.property_id) return { property_id: body.property_id };
  if (body.inspection_id) return { inspection_id: body.inspection_id };
  return null;
}

// Extract the complete editable measurement document from an authoritative revision detail. Routing and
// command fields stay on the mutation body; these are the values that must participate in conflict merge.
function _cloneJson(value) { return value == null ? value : JSON.parse(JSON.stringify(value)); }
function _ref(row, preferred, fallback) {
  const value = row && row[preferred] != null ? row[preferred] : (row && row[fallback] != null ? row[fallback] : null);
  return value == null || value === "" ? null : String(value);
}
function measurementDocumentFromRevision(src) {
  if (!src || typeof src !== "object") return null;
  const structures = (src.structures || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    name: row.name || "",
    structure_type: row.structure_type || "main_house",
    included_in_scope: row.included_in_scope !== false,
    stories: row.stories == null ? null : row.stories,
    approx_height_ft: row.approx_height_ft == null ? null : row.approx_height_ft,
    attachment: row.attachment == null ? null : row.attachment,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const facets = (src.facets || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    structure_ref: _ref(row, "structure_ref", "structure_id"),
    facet_label: row.facet_label || "",
    pitch_rise: row.pitch_rise == null ? null : row.pitch_rise,
    area_sqft: row.area_sqft == null ? 0 : row.area_sqft,
    width_ft: row.width_ft == null ? null : row.width_ft,
    length_ft: row.length_ft == null ? null : row.length_ft,
    position_offset_ft: row.position_offset_ft == null ? null : row.position_offset_ft,
    orientation_azimuth: row.orientation_azimuth == null ? null : row.orientation_azimuth,
    roof_material: row.roof_material == null ? null : row.roof_material,
    notes: row.notes == null ? null : row.notes,
    geometry: row.geometry == null ? null : _cloneJson(row.geometry),
    sort: row.sort == null ? index : row.sort,
  }));
  const edges = (src.edges || []).map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    edge_type: row.edge_type || "eave",
    length_ft: row.length_ft == null ? 0 : row.length_ft,
    facet_ref: _ref(row, "facet_ref", "facet_id"),
    facet_ref_secondary: _ref(row, "facet_ref_secondary", "facet_id_secondary"),
    label: row.label == null ? null : row.label,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const sourcePenetrations = src.penetrations != null ? src.penetrations : (src.pens || []);
  const penetrations = sourcePenetrations.map((row, index) => ({
    ref: _ref(row, "ref", "id"),
    pen_type: row.pen_type || "pipe_boot",
    quantity: row.quantity == null ? 1 : row.quantity,
    facet_ref: _ref(row, "facet_ref", "facet_id"),
    diameter_in: row.diameter_in == null ? null : row.diameter_in,
    width_in: row.width_in == null ? null : row.width_in,
    length_in: row.length_in == null ? null : row.length_in,
    notes: row.notes == null ? null : row.notes,
    sort: row.sort == null ? index : row.sort,
  }));
  const out = {
    structures,
    facets,
    edges,
    penetrations,
    summary: _cloneJson(src.summary || {}),
  };
  for (const key of ["source", "provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(src, key)) out[key] = _cloneJson(src[key]);
  }
  return out;
}

// Coalescing rule: once a measurement_update is pending, every later local edit retains that row's ORIGINAL
// base. Falling back to the current optimistic cache would manufacture a false base and permit data loss.
function chooseDurableMeasurementBase(authoritative, pending) {
  if (pending && pending.kind === "measurement_update") {
    if (!pending.base_body || pending.base_token == null || pending.base_token === "") {
      return { ok: false, reason: "missing_durable_base" };
    }
    const normalizedBase = measurementDocumentFromRevision(pending.base_body);
    if (!normalizedBase) return { ok: false, reason: "missing_durable_base" };
    return { ok: true, baseBody: normalizedBase, baseToken: String(pending.base_token) };
  }
  const token = authoritative && (authoritative.base_token || authoritative.updated_at || authoritative.if_match);
  const body = authoritative && authoritative.base_body
    ? _cloneJson(authoritative.base_body)
    : measurementDocumentFromRevision(authoritative);
  if (!body || token == null || token === "") return { ok: false, reason: "missing_authoritative_base" };
  return { ok: true, baseBody: body, baseToken: String(token) };
}

// A Keep-Mine merge is legal only when the durable base token is exactly the token used by the failed PUT.
// Legacy rows are preserved for explicit review rather than blindly re-sending an entire stale snapshot.
function measurementConflictMergeInputs(mutation, serverDetail) {
  if (!mutation || mutation.kind !== "measurement_update") return { ok: false, reason: "not_measurement_update" };
  if (!mutation.base_body || mutation.base_token == null || mutation.base_token === "") {
    return { ok: false, reason: "missing_durable_base" };
  }
  if (String(mutation.base_token) !== String(mutation.ifMatch || "")) {
    return { ok: false, reason: "base_token_mismatch" };
  }
  const office = measurementDocumentFromRevision(serverDetail);
  if (!office || !serverDetail || serverDetail.updated_at == null) {
    return { ok: false, reason: "missing_office_detail" };
  }
  return {
    ok: true,
    base: measurementDocumentFromRevision(mutation.base_body),
    field: measurementDocumentFromRevision(mutation.body || {}),
    office,
    officeToken: String(serverDetail.updated_at),
  };
}

function buildMergedMeasurementBody(fieldBody, merged) {
  const next = _cloneJson(fieldBody || {}) || {};
  const normalized = measurementDocumentFromRevision(merged) || {
    structures: [], facets: [], edges: [], penetrations: [], summary: {},
  };
  next.structures = normalized.structures;
  next.facets = normalized.facets;
  next.edges = normalized.edges;
  next.penetrations = normalized.penetrations;
  next.summary = normalized.summary;
  for (const key of ["source", "provider", "report_id", "reported_area_sqft", "notes"]) {
    if (Object.prototype.hasOwnProperty.call(normalized, key)) next[key] = _cloneJson(normalized[key]);
  }
  return next;
}

// A newer local edit (higher generation) landed while the ack was in flight → the ack is stale for the
// currently-stored row. Its authoritative caches still advance, but its drafts must NEVER be retired.
function isSupersededAck(storedRow, ack) {
  if (!storedRow || !ack) return false;
  return Number(storedRow.mutation_generation) !== Number(ack.mutation_generation);
}

// Reducer for the durable CREATE draft slot: retire it ONLY when its client_id matches the acked mutation.
function retireCreateDraft(cur, clientId) {
  return (cur && cur.client_id === clientId) ? null : cur;
}

// Reducer for the working-draft slot on ack: clear it ONLY when it belongs to the same base/client
// generation AND holds no newer edit. A content-bearing working draft is a NEWER in-progress edit and is
// always preserved (never deleted by a late acknowledgement).
function planMeasurementWorkingAck(wd, { kind, clientId, revisionId } = {}) {
  if (!wd || !wd.working) return wd || null;
  if (workingDraftHasContent(wd)) return wd; // newer in-progress edit → preserve verbatim
  const belongs = kind === "measurement"
    ? (wd.local_client_id != null && wd.local_client_id === clientId)
    : (wd.base && revisionId != null && String(wd.base.id) === String(revisionId));
  return belongs ? null : wd;
}

// Decide which measurement the Field screen should show, and the truthful sync status. Pure; no I/O.
// `pendingCreate` / `pendingUpdate` are the FULL durable mutation rows (any state) or null.
function resolveMeasurementView({ serverDetail, serverStale, optimistic, draft, pendingUpdate, pendingCreate, isSyncing } = {}) {
  // 1) A brand-new measurement (create) not yet acknowledged: the local draft IS the working copy.
  if (pendingCreate && draft && pendingCreate.state !== "synced") {
    const st = measurementSyncState(pendingCreate, isSyncing);
    return { kind: "local_draft", detail: draft, status: st.status, conflict: st.conflict, mutationState: st.state, failed: st.failed, reason: st.reason };
  }

  // 2) An existing revision with unsynced local edits.
  if (pendingUpdate && pendingUpdate.state !== "synced" && optimistic) {
    // Durable server-side conflict (a real 409): the mutation carries the authoritative server copy.
    if (pendingUpdate.state === "conflict") {
      return { kind: "conflict", detail: optimistic, serverDetail: pendingUpdate.serverValue || serverDetail, status: STATUS.conflict, conflict: true, mutationState: "conflict", reason: pendingUpdate.error || null };
    }
    // Locked/immutable revision: the server revision is authoritative; offer the new-revision path.
    if (pendingUpdate.state === "locked") {
      return { kind: "locked", detail: serverDetail || optimistic, status: STATUS.locked, conflict: false, locked: true, mutationState: "locked", reason: pendingUpdate.error || null };
    }
    // A failed mutation preserves local work but is shown truthfully as failed (never "waiting").
    if (pendingUpdate.state === "failed") {
      return { kind: "local_update", detail: optimistic, status: STATUS.failed, conflict: false, mutationState: "failed", failed: true, reason: pendingUpdate.error || "Sync failed — retry needed" };
    }
    // Pending: Office changed the SAME revision since our base — only trustable when we actually reached
    // the server (a stale/offline read cannot prove a change). Explicit conflict, never a silent overwrite.
    const base = pendingUpdate.ifMatch != null ? String(pendingUpdate.ifMatch) : null;
    const serverVer = serverDetail && serverDetail.updated_at != null ? String(serverDetail.updated_at) : null;
    if (!serverStale && serverVer != null && base != null && serverVer !== base) {
      return { kind: "conflict", detail: optimistic, serverDetail, status: STATUS.conflict, conflict: true, mutationState: "pending" };
    }
    return { kind: "local_update", detail: optimistic, status: isSyncing ? STATUS.syncing : STATUS.waiting, conflict: false, mutationState: "pending" };
  }

  // 3) No pending local work: the authoritative server copy (or the last cached server copy offline).
  if (serverDetail) {
    return { kind: serverStale ? "server_cached" : "server", detail: serverDetail, status: STATUS.synced, conflict: false, stale: !!serverStale, mutationState: "none" };
  }
  if (draft) {
    const st = measurementSyncState(pendingCreate && pendingCreate.state !== "synced" ? pendingCreate : null, isSyncing);
    return { kind: "local_draft", detail: draft, status: st.state === "none" ? STATUS.savedLocal : st.status, conflict: false, mutationState: st.state, failed: st.failed, reason: st.reason };
  }
  return { kind: "empty", detail: null, status: null, conflict: false, mutationState: "none" };
}

// Transform a superseded CREATE row into an UPDATE of the just-created server revision (P0 data-loss fix):
// the newer local body must be APPLIED, not lost to an idempotent create replay. Preserves the newer body,
// generation, scope and local_edit_generation; resets the network/result fields; becomes a PUT.
function buildConvertedUpdateMutation(m, revisionId, ifMatch, serverBase) {
  const cid = `measurement-update:${String(revisionId)}`;
  const authoritativeBase = measurementDocumentFromRevision(serverBase);
  return {
    ...m,
    client_id: cid,
    idempotency_key: cid,
    kind: "measurement_update",
    method: "PUT",
    path: `/mobile/measurements/${String(revisionId)}`,
    ifMatch,
    base_body: authoritativeBase,
    base_token: ifMatch == null ? null : String(ifMatch),
    server_id: String(revisionId),
    serverValue: null,
    error: null,
    errorCode: null,
    attempts: 0,
    state: "pending",
  };
}

// Rebase a create's working draft onto the newly-created server revision id + token, so continued editing
// targets the real revision. Only touches the working draft that belongs to this create.
function rebaseWorkingDraftToRevision(wd, { oldClientId, revisionId, ifMatch } = {}) {
  if (!wd || !wd.working) return wd || null;
  if (wd.local_client_id != null && oldClientId != null && wd.local_client_id !== oldClientId) return wd;
  return { ...wd, base: { id: String(revisionId), if_match: ifMatch }, local_client_id: null };
}

module.exports = {
  STATUS,
  resolveMeasurementView,
  measurementSyncState,
  upsertRevision,
  measScopeFromBody,
  measurementDocumentFromRevision,
  chooseDurableMeasurementBase,
  measurementConflictMergeInputs,
  buildMergedMeasurementBody,
  isSupersededAck,
  retireCreateDraft,
  planMeasurementWorkingAck,
  buildConvertedUpdateMutation,
  rebaseWorkingDraftToRevision,
};
