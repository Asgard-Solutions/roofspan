"use strict";
/*
 * RoofSpan Field — device sync DIAGNOSTICS (pure; no RN/IO). Records, per mutation, the fields an
 * engineer needs to explain a stuck device: mutation state, HTTP result, revision id, server token
 * (updated_at / document_version), and the cache source — AND tracks the last successful PULL
 * (Office→Field read) SEPARATELY from the last successful PUSH (Field→Office write), because "we synced"
 * must never conflate the two directions.
 */

// Normalize one mutation diagnostic record (drops nothing meaningful, coerces types deterministically).
function buildMutationDiagnostic({ clientId, kind, state, httpResult, revisionId, serverToken, cacheSource, error } = {}, now = () => new Date().toISOString()) {
  return {
    client_id: clientId != null ? String(clientId) : null,
    kind: kind || null,
    state: state || null,
    http_result: httpResult != null ? String(httpResult) : "ok",
    revision_id: revisionId != null ? String(revisionId) : null,
    server_token: serverToken != null ? String(serverToken) : null,   // updated_at / document_version
    cache_source: cacheSource || null,                                  // ack | server | cache | offline
    error: error || null,
    at: now(),
  };
}

function createDiagnostics({ now = () => new Date().toISOString(), capacity = 50 } = {}) {
  let lastPullAt = null;   // last successful Office→Field READ
  let lastPushAt = null;   // last successful Field→Office WRITE
  const records = [];      // bounded ring of recent per-mutation diagnostics (newest last)

  return {
    recordPull() { lastPullAt = now(); return lastPullAt; },
    recordPush() { lastPushAt = now(); return lastPushAt; },
    recordMutation(fields) {
      const rec = buildMutationDiagnostic(fields, now);
      records.push(rec);
      while (records.length > capacity) records.shift();
      return rec;
    },
    // Diagnostic view: last pull and last push are ALWAYS reported separately.
    snapshot() {
      return {
        last_successful_pull_at: lastPullAt,
        last_successful_push_at: lastPushAt,
        mutations: records.slice(),
      };
    },
  };
}

module.exports = { buildMutationDiagnostic, createDiagnostics };
