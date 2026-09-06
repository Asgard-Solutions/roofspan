"use strict";
/*
 * RoofSpan Field — device sync DIAGNOSTICS (pure; no RN/IO). Records, per mutation, the fields an
 * engineer needs to explain a stuck device, and tracks the honest sync timestamps SEPARATELY:
 *   - last_push_attempt_at    : a Field→Office push CYCLE started (success or not)
 *   - last_successful_push_at : at least one mutation received an AUTHORITATIVE success ack
 *   - last_successful_pull_at : an Office→Field read (watermark/canonical) succeeded
 * The bounded ring + timestamps are snapshot()'d to scoped SQLite by the runtime so diagnostics SURVIVE
 * the very failure (app kill / force-stop / restart) they are meant to diagnose; hydrate() restores them.
 *
 * PRIVACY: records carry ONLY operational metadata (state, HTTP status, relay error code, path category,
 * mutation generation, revision id, server token, cache source, recovery action). They NEVER include
 * access/refresh tokens, device credentials, homeowner-sensitive notes, or photo payloads.
 */

function _s(v) { return v != null ? String(v) : null; }
function _n(v) { return v != null && v !== "" && !Number.isNaN(Number(v)) ? Number(v) : null; }

// Normalize one mutation diagnostic record. Only operational metadata — never secrets/PII/payloads.
function buildMutationDiagnostic(fields = {}, now = () => new Date().toISOString()) {
  const {
    clientId, kind, state, httpResult, httpStatus, relayErrorCode, pathCategory,
    mutationGeneration, revisionId, serverToken, cacheSource, recoveryAction, error,
  } = fields;
  return {
    client_id: _s(clientId),
    kind: kind || null,
    state: state || null,
    http_result: httpResult != null ? String(httpResult) : "ok",
    http_status: _n(httpStatus),
    relay_error_code: relayErrorCode != null ? String(relayErrorCode) : null,
    path_category: pathCategory || null,                 // e.g. /api/measurements (id-free)
    mutation_generation: _n(mutationGeneration),
    revision_id: _s(revisionId),
    server_token: _s(serverToken),                        // updated_at / document_version
    cache_source: cacheSource || null,                    // ack | server | cache | offline
    recovery_action: recoveryAction || null,              // retire | rebase | convert | conflict | none
    error: error || null,                                 // short message only (no PII/payloads)
    at: now(),
  };
}

function createDiagnostics({ now = () => new Date().toISOString(), capacity = 50 } = {}) {
  let lastPushAttemptAt = null;   // a Field→Office push cycle STARTED
  let lastPushOkAt = null;        // at least one mutation ACKNOWLEDGED (authoritative success)
  let lastPullAt = null;          // last successful Office→Field READ
  let records = [];               // bounded ring of recent per-mutation diagnostics (newest last)

  return {
    recordPushAttempt() { lastPushAttemptAt = now(); return lastPushAttemptAt; },
    recordPushSuccess() { lastPushOkAt = now(); return lastPushOkAt; },
    recordPull() { lastPullAt = now(); return lastPullAt; },
    recordMutation(fields) {
      const rec = buildMutationDiagnostic(fields, now);
      records.push(rec);
      while (records.length > capacity) records.shift();
      return rec;
    },
    // Restore a previously-persisted snapshot after an app kill/restart (best-effort, bounded).
    hydrate(snap) {
      if (!snap || typeof snap !== "object") return;
      lastPushAttemptAt = snap.last_push_attempt_at || lastPushAttemptAt;
      lastPushOkAt = snap.last_successful_push_at || lastPushOkAt;
      lastPullAt = snap.last_successful_pull_at || lastPullAt;
      if (Array.isArray(snap.mutations)) records = snap.mutations.slice(-capacity);
    },
    snapshot() {
      return {
        last_push_attempt_at: lastPushAttemptAt,
        last_successful_push_at: lastPushOkAt,
        last_successful_pull_at: lastPullAt,
        mutations: records.slice(),
      };
    },
  };
}

module.exports = { buildMutationDiagnostic, createDiagnostics };
