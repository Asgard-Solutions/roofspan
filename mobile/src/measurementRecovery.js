"use strict";
/*
 * RoofSpan Field — one-time startup measurement RECOVERY (pure decision layer; no RN).
 *
 * Phones that were running the app BEFORE the measurement acknowledgement lifecycle shipped can be stuck
 * in the bad state: a `measurement`/`measurement_update` that already SYNCED but whose local draft was
 * never retired (so the field keeps showing the local copy), a `failed` mutation shown as merely "waiting",
 * a durable `conflict` that was never surfaced, or an orphaned working draft shadowing Office forever.
 *
 * This module supplies the PURE, deterministic decisions the startup routine (sync.recoverMeasurementsOnStartup)
 * executes against the serialized storage boundary. It NEVER wipes app data and NEVER silently deletes
 * legitimate unsynced work — every branch either heals safely or preserves the work for explicit resolution.
 */

const { workingDraftHasContent } = require("./measurementDraftPriority");
const { measScopeFromBody } = require("./measurementReconcile");

// ---- canonical measurement comparison (works across the edit-shape AND the server-detail shape) ----
function _num(v) { if (v === "" || v == null) return null; const n = Number(v); return Number.isFinite(n) ? n : null; }
function _cmp(a, b) { const x = JSON.stringify(a), y = JSON.stringify(b); return x < y ? -1 : (x > y ? 1 : 0); }
function _structures(list) {
  return (list || []).map((s) => ({
    name: s.name || "", type: s.structure_type || "main_house", scope: s.included_in_scope !== false,
    stories: _num(s.stories), height: _num(s.approx_height_ft), attach: s.attachment || null,
    notes: s.notes || "",
  })).sort(_cmp);
}
function _facets(list) {
  return (list || []).map((f) => ({
    label: f.facet_label || "", pitch: _num(f.pitch_rise), area: _num(f.area_sqft),
    w: _num(f.width_ft), l: _num(f.length_ft), off: _num(f.position_offset_ft),
    structure: _rel(f.structure_id != null ? f.structure_id : f.structure_ref),   // roof-plane → structure assignment
    material: f.roof_material || f.material || "",                                  // roof material
    azimuth: _num(f.orientation_azimuth != null ? f.orientation_azimuth : f.azimuth), // orientation
    geometry: _geom(f.geometry),                                                    // geometry
    notes: f.notes || "",                                                           // roof-plane notes
  })).sort(_cmp);
}
function _edges(list) {
  return (list || []).map((e) => ({
    type: e.edge_type || "", len: Math.round((_num(e.length_ft) || 0) * 100) / 100,
    label: e.label || "", notes: e.notes || "",                                     // roof-line label + notes
    plane: _rel(e.facet_id != null ? e.facet_id : e.facet_ref),                     // primary plane assignment
    plane2: _rel(e.facet_id_secondary != null ? e.facet_id_secondary : e.facet_ref_secondary), // secondary plane
  })).sort(_cmp);
}
function _pens(list) {
  return (list || []).filter((p) => (parseInt(p.quantity, 10) || 0) > 0).map((p) => ({
    type: p.pen_type || "", qty: parseInt(p.quantity, 10) || 0,
    plane: _rel(p.facet_id != null ? p.facet_id : p.facet_ref),                     // penetration → plane assignment
    diameter: _num(p.diameter_in), w: _num(p.width_in), l: _num(p.length_in),       // dimensions
    notes: p.notes || "",                                                           // penetration notes
  })).sort(_cmp);
}
// Stable relationship identity (a temporary React key is ignored; a real id/ref reference is significant).
function _rel(v) { return v == null ? null : String(v); }
// Geometry is a nested business value (vertices/points/path) — compared verbatim after a stable stringify.
function _geom(g) { if (g == null) return null; try { return JSON.parse(JSON.stringify(g)); } catch (e) { return null; } }
function _summary(sm) {
  sm = sm || {};
  const out = {};
  Object.keys(sm).sort().forEach((k) => {
    const v = sm[k];
    if (v === null || v === undefined || v === "" || typeof v === "object") return; // skip empties + nested
    out[k] = typeof v === "number" ? v : (v === true || v === false ? v : String(v));
  });
  return out;
}

// Normalize either a working draft (top-level structures/facets/edges/pens) or a server revision detail
// (structures/facets/edges/penetrations) into one comparable canonical form.
function canonicalMeasurement(src) {
  src = src || {};
  const pens = src.pens != null ? src.pens : src.penetrations;
  return {
    structures: _structures(src.structures),
    facets: _facets(src.facets),
    edges: _edges(src.edges),
    pens: _pens(pens),
    summary: _summary(src.summary),
  };
}

// STRICT equality — returns true ONLY when the content is provably identical. Any difference (or missing
// base) yields false, so a working draft is never cleared on an uncertain compare (never lose real work).
function canonicalEqual(a, b) {
  return JSON.stringify(canonicalMeasurement(a)) === JSON.stringify(canonicalMeasurement(b));
}

// One shared, COMPLETE canonical fingerprint over every persisted measurement field + stable relationship,
// generated from the same edit-shape payload the backend receives (temporary React keys ignored). Recorded
// as base_fingerprint when a working draft is created so auto-clear can prove "no net edit" exactly.
function canonicalFingerprint(payload) {
  return JSON.stringify(canonicalMeasurement(payload));
}

// The working-draft cache key encodes its measurement scope: measurement_working:measurement_scope:{kind}:{id}
function parseWorkingScope(name) {
  const m = /measurement_scope:(lead|property|inspection):(.+)$/.exec(String(name || ""));
  if (!m) return null;
  if (m[1] === "lead") return { lead_id: m[2] };
  if (m[1] === "property") return { property_id: m[2] };
  return { inspection_id: m[2] };
}

function parseUpdateRevisionId(clientId) {
  const s = String(clientId || "");
  return s.startsWith("measurement-update:") ? s.slice("measurement-update:".length) : null;
}

// Orphaned working-draft decision (spec: never silently delete):
//   - active mutation for this scope/base       -> keep (still in flight; not orphaned)
//   - empty                                      -> clear (safe; nothing to lose)
//   - identical to its recorded base revision    -> clear (mirrors Office; no real edit)
//   - differs AND Office has advanced past base  -> conflict (preserve + require explicit resolution)
//   - anything else (differs, base unknown)      -> keep (preserve the unsynced work)
function classifyOrphanWorkingDraft({ wd, hasActiveMutation, baseRevision } = {}) {
  if (!wd || !wd.working) return { action: "keep", reason: "not_working" };
  if (hasActiveMutation) return { action: "keep", reason: "active_mutation" };
  if (!workingDraftHasContent(wd)) return { action: "clear", reason: "empty" };
  const baseTok = wd.base && wd.base.if_match != null ? String(wd.base.if_match) : null;
  const serverTok = baseRevision && baseRevision.updated_at != null ? String(baseRevision.updated_at) : null;
  const tokenMatches = baseTok == null || serverTok == null || baseTok === serverTok;
  // STRONGEST path: a complete base_fingerprint recorded at draft creation proves whether ANY persisted
  // field changed since the rep opened it — no net edit AND the base token still matches AND no active
  // mutation → the draft is obsolete and safe to clear.
  if (wd.base_fingerprint != null) {
    if (canonicalFingerprint(wd) === wd.base_fingerprint && tokenMatches) return { action: "clear", reason: "unchanged_since_base" };
    if (baseTok != null && serverTok != null && baseTok !== serverTok && baseRevision) {
      return { action: "conflict", reason: "office_advanced", serverDetail: baseRevision };
    }
    return { action: "keep", reason: "edited" };
  }
  // Fallback (older drafts without a fingerprint): complete canonical equality against the base revision.
  if (baseRevision) {
    if (canonicalEqual(wd, baseRevision)) return { action: "clear", reason: "identical_to_base" };
    if (baseTok != null && serverTok != null && baseTok !== serverTok) {
      return { action: "conflict", reason: "office_advanced", serverDetail: baseRevision };
    }
  }
  return { action: "keep", reason: "differs" };
}

// A failed/conflict mutation the rep must be routed to (preserve both versions; require explicit choice).
function recoveryAttentionItem(mutation) {
  if (!mutation || (mutation.state !== "conflict" && mutation.state !== "failed")) return null;
  const revisionId = mutation.kind === "measurement_update"
    ? parseUpdateRevisionId(mutation.client_id)
    : (mutation.serverValue && mutation.serverValue.id ? String(mutation.serverValue.id) : null);
  return {
    kind: mutation.state,
    mutationKind: mutation.kind,
    client_id: mutation.client_id,
    revisionId,
    scope: measScopeFromBody(mutation.body),
    error: mutation.error || null,
  };
}

// Pure classification of the ON-DEVICE queue at startup (restart-after-ack safety). synced measurement
// creates/updates are settled (their drafts retired by the caller); failed/conflict rows are surfaced for
// explicit resolution and NEVER auto-resolved. pending rows are left alone.
function planStartupRecovery(mutations) {
  const settle = [], conflicts = [], failures = [];
  for (const m of (mutations || [])) {
    if (!m || (m.kind !== "measurement" && m.kind !== "measurement_update")) continue;
    if (m.state === "conflict") { const it = recoveryAttentionItem(m); if (it) conflicts.push(it); continue; }
    if (m.state === "failed") { const it = recoveryAttentionItem(m); if (it) failures.push(it); continue; }
    if (m.state === "synced") settle.push(m);
  }
  return { settle, conflicts, failures };
}

module.exports = {
  canonicalMeasurement,
  canonicalEqual,
  canonicalFingerprint,
  parseWorkingScope,
  parseUpdateRevisionId,
  classifyOrphanWorkingDraft,
  recoveryAttentionItem,
  planStartupRecovery,
};
