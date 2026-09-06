"use strict";
/*
 * RoofSpan Field — PURE derivation of the salesperson-facing GLOBAL sync status (no RN/IO).
 *
 * The runtime (sync.js) supplies raw mutation-state counts + timestamps; this module turns them into
 * the honest, separated status the UI shows. Two rules the spec mandates:
 *   1. "Waiting to sync" means ONLY pending (in-flight/queued) work — a failed / conflict / locked item
 *      is NEVER described as "waiting".
 *   2. Full convergence requires an ALL-CLEAR queue: no pending, failed, conflict, or locked mutation.
 *      (The last_fully_converged_at timestamp is advanced by the runtime only when this is true.)
 */

function countStates(mutations) {
  const counts = { pending: 0, failed: 0, conflict: 0, synced: 0, locked: 0 };
  for (const m of mutations || []) {
    const s = m && m.state;
    if (s) counts[s] = (counts[s] || 0) + 1;
  }
  return counts;
}

function isFullyConverged(counts = {}) {
  return (counts.pending || 0) === 0 && (counts.failed || 0) === 0 &&
         (counts.conflict || 0) === 0 && (counts.locked || 0) === 0;
}

function deriveSyncStatus(counts = {}, { syncing = false } = {}) {
  const pending_count = counts.pending || 0;
  const failed_count = counts.failed || 0;
  const conflict_count = counts.conflict || 0;
  const locked_count = counts.locked || 0;
  const waiting = pending_count;                 // ONLY pending — never failed/conflict/locked
  const fully_converged = isFullyConverged(counts);

  let label;
  if (syncing) label = "Synchronizing…";
  else if (conflict_count > 0) label = `${conflict_count} sync issue${conflict_count > 1 ? "s" : ""} to review`;
  else if (failed_count > 0) label = `${failed_count} change${failed_count > 1 ? "s" : ""} failed to sync — retry needed`;
  else if (locked_count > 0) label = `${locked_count} locked revision sketch${locked_count > 1 ? "es" : ""} — new revision needed`;
  else if (pending_count > 0) label = `${pending_count} change${pending_count > 1 ? "s" : ""} waiting to sync`;
  else label = "All changes synced";

  return { pending_count, failed_count, conflict_count, locked_count, waiting, fully_converged, label };
}

module.exports = { countStates, isFullyConverged, deriveSyncStatus };
