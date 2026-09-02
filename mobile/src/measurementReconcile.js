"use strict";
/*
 * RoofSpan Field — measurement view reconciliation (pure, Node-testable; no RN).
 *
 * ROOT CAUSE this fixes: the screen's read-through (cache.measurement) always overwrites the local
 * optimistic detail with whatever the server currently holds. For an EXISTING revision the salesperson's
 * freshly-saved-but-unsynced edit lives only in the optimistic detail cache + a pending measurement_update
 * mutation, so a normal reload replaced it with the OLDER server copy and the work "disappeared".
 *
 * Rule enforced here: the newest DURABLE LOCAL unsynced measurement is the working copy until Office
 * acknowledges it, the user discards it, or Office changed the SAME revision (a real conflict that must be
 * resolved explicitly — never silently overwritten either way).
 */

function _status(kind, isSyncing) {
  if (kind === "conflict") return "Needs review";
  if (kind === "local_update" || kind === "local_draft") return isSyncing ? "Syncing" : "Waiting to sync";
  return "Synced";
}

// Decide which measurement the Field screen should show, and the truthful sync status.
// Inputs are all plain values the screen already has; no I/O here.
function resolveMeasurementView({ serverDetail, serverStale, optimistic, draft, pendingUpdate, pendingCreate, isSyncing } = {}) {
  // 1) A brand-new measurement (create) not yet acknowledged: the local draft IS the working copy.
  if (pendingCreate && draft) {
    return { kind: "local_draft", detail: draft, status: _status("local_draft", isSyncing), conflict: false };
  }

  // 2) An existing revision with unsynced local edits (pending measurement_update).
  if (pendingUpdate && optimistic) {
    const base = pendingUpdate.ifMatch != null ? String(pendingUpdate.ifMatch) : null;
    const serverVer = serverDetail && serverDetail.updated_at != null ? String(serverDetail.updated_at) : null;
    // Office changed the SAME revision since our base — only trustable when we actually reached the server
    // (a stale/offline read cannot prove a change). This is an explicit conflict, not a silent overwrite.
    if (!serverStale && serverVer != null && base != null && serverVer !== base) {
      return { kind: "conflict", detail: optimistic, serverDetail, status: _status("conflict"), conflict: true };
    }
    // Server unchanged (or we're offline): the newer local optimistic copy wins.
    return { kind: "local_update", detail: optimistic, status: _status("local_update", isSyncing), conflict: false };
  }

  // 3) No pending local work: the authoritative server copy (or the last cached server copy offline).
  if (serverDetail) {
    return { kind: serverStale ? "server_cached" : "server", detail: serverDetail, status: "Synced", conflict: false, stale: !!serverStale };
  }
  if (draft) return { kind: "local_draft", detail: draft, status: _status("local_draft", isSyncing), conflict: false };
  return { kind: "empty", detail: null, status: null, conflict: false };
}

module.exports = { resolveMeasurementView };
