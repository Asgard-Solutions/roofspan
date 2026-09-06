"use strict";
/*
 * RoofSpan Field — CENTRAL, LEAD-AWARE measurement sync coordinator (pure decision core; no RN/IO).
 *
 * Synchronization is no longer owned by whichever screen happens to be open. This coordinator is keyed by
 * lead (or property/inspection scope) AND revision, tracks authoritative WATERMARKS for each revision and
 * each structure sketch, and coalesces the many refresh triggers (lead opened, Measurements focus, app
 * foreground, connectivity return, acknowledgement, manual sync, Office "changed" invalidation). It lets
 * Field decide whether its cached revision/sketches are current from the watermark alone — never guessed
 * from local-draft presence. The runtime wrapper (sync.js) performs the actual cache IO.
 */

// Validate + normalize the relay `measurement_changed` invalidation event into a scope + watermark.
function parseInvalidation(evt) {
  evt = evt || {};
  let leadScope = null;
  if (evt.lead_id) leadScope = { lead_id: String(evt.lead_id) };
  else if (evt.property_id) leadScope = { property_id: String(evt.property_id) };
  else if (evt.inspection_id) leadScope = { inspection_id: String(evt.inspection_id) };
  return {
    leadScope,
    measurementSetId: evt.measurement_set_id != null ? String(evt.measurement_set_id) : null,
    revisionId: evt.revision_id != null ? String(evt.revision_id) : null,
    updatedAt: evt.updated_at != null ? String(evt.updated_at) : null,
  };
}

// Force triggers always refresh; a plain periodic/foreground trigger honors a min interval unless the
// lead is marked dirty (an invalidation arrived) — so we converge fast but never hammer Office.
const FORCE = new Set(["office_invalidation", "acknowledgement", "connectivity", "manual", "lead_open", "measurements_focus"]);

function createMeasurementSyncCoordinator({ now = () => Date.now(), minIntervalMs = 4000 } = {}) {
  const leadKeyOf = (scope) => {
    if (!scope) return null;
    if (scope.lead_id) return `lead:${scope.lead_id}`;
    if (scope.property_id) return `property:${scope.property_id}`;
    if (scope.inspection_id) return `inspection:${scope.inspection_id}`;
    return null;
  };
  const active = new Map();          // leadKey -> { scope, lastRefreshAt, dirty }
  const revWatermark = new Map();    // revisionId -> authoritative updated_at (ISO)
  const sketchWatermark = new Map(); // `${revisionId}:${structureId}` -> document_version

  function registerActiveLead(scope) {
    const k = leadKeyOf(scope);
    if (!k) return null;
    if (!active.has(k)) active.set(k, { scope, lastRefreshAt: 0, dirty: true });
    return k;
  }
  function activeLeads() { return [...active.values()].map((v) => v.scope); }
  function isActive(scope) { const k = leadKeyOf(scope); return !!(k && active.has(k)); }

  // Authoritative watermarks always come from Office; adopt the CHRONOLOGICALLY latest (ISO strings sort
  // chronologically) so an out-of-order older event can never regress what we already know.
  function noteRevisionWatermark(revisionId, updatedAt) {
    if (!revisionId || updatedAt == null) return;
    const id = String(revisionId), next = String(updatedAt);
    const cur = revWatermark.get(id);
    if (cur == null || next > cur) revWatermark.set(id, next);
  }
  function noteSketchWatermark(revisionId, structureId, documentVersion) {
    if (!revisionId || !structureId) return;
    const key = `${revisionId}:${structureId}`;
    const next = Number(documentVersion) || 0;
    const cur = sketchWatermark.get(key);
    if (cur == null || next > cur) sketchWatermark.set(key, next);
  }
  function revisionWatermark(revisionId) { return revWatermark.get(String(revisionId)) || null; }
  function sketchVersion(revisionId, structureId) { const v = sketchWatermark.get(`${revisionId}:${structureId}`); return v == null ? null : v; }

  // Is a cached revision BEHIND the authoritative watermark? (No guessing from draft presence.)
  function isRevisionStale(revisionId, cachedUpdatedAt) {
    const w = revWatermark.get(String(revisionId));
    if (w == null) return false;              // no known authoritative watermark → not provably stale
    if (cachedUpdatedAt == null) return true; // we know a server version but hold nothing cached
    return String(cachedUpdatedAt) !== String(w);
  }
  function isSketchStale(revisionId, structureId, cachedVersion) {
    const w = sketchWatermark.get(`${revisionId}:${structureId}`);
    if (w == null) return false;
    return Number(cachedVersion || 0) !== Number(w);
  }

  function shouldRefresh(trigger, scope) {
    const k = leadKeyOf(scope);
    if (!k) return false;
    const st = active.get(k) || { lastRefreshAt: 0, dirty: true };
    if (FORCE.has(trigger)) return true;
    if (st.dirty) return true;
    return (now() - (st.lastRefreshAt || 0)) >= minIntervalMs;
  }
  function markRefreshed(scope) {
    const k = leadKeyOf(scope);
    if (!k) return;
    const st = active.get(k) || { scope };
    active.set(k, { ...st, scope, lastRefreshAt: now(), dirty: false });
  }

  // Office said a measurement/sketch changed → mark the lead dirty (force next refresh) + adopt watermark.
  function invalidate(evt) {
    const parsed = parseInvalidation(evt);
    if (!parsed.leadScope) return null;
    const k = leadKeyOf(parsed.leadScope);
    const st = active.get(k) || { scope: parsed.leadScope };
    active.set(k, { ...st, scope: parsed.leadScope, dirty: true });
    if (parsed.revisionId && parsed.updatedAt != null) noteRevisionWatermark(parsed.revisionId, parsed.updatedAt);
    return parsed;
  }

  return {
    leadKeyOf, registerActiveLead, activeLeads, isActive,
    noteRevisionWatermark, noteSketchWatermark, revisionWatermark, sketchVersion,
    isRevisionStale, isSketchStale, shouldRefresh, markRefreshed, invalidate,
  };
}

module.exports = { createMeasurementSyncCoordinator, parseInvalidation };
