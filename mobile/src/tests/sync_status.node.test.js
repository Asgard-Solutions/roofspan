"use strict";
// Pure tests for the GLOBAL sync-status derivation (spec: separated counts + honest convergence).
const assert = require("assert");
const { countStates, isFullyConverged, deriveSyncStatus } = require("../syncStatus");

let n = 0;
function ok(msg) { n += 1; console.log(`  ok ${n} - ${msg}`); }

// countStates tallies every state independently.
(() => {
  const c = countStates([
    { state: "pending" }, { state: "pending" }, { state: "failed" },
    { state: "conflict" }, { state: "locked" }, { state: "synced" }, { state: null },
  ]);
  assert.strictEqual(c.pending, 2);
  assert.strictEqual(c.failed, 1);
  assert.strictEqual(c.conflict, 1);
  assert.strictEqual(c.locked, 1);
  assert.strictEqual(c.synced, 1);
  ok("countStates tallies pending/failed/conflict/locked/synced separately");
})();

// A failed item is NEVER "waiting to sync" and NEVER counts toward `waiting`.
(() => {
  const s = deriveSyncStatus({ pending: 0, failed: 1 });
  assert.strictEqual(s.failed_count, 1);
  assert.strictEqual(s.pending_count, 0);
  assert.strictEqual(s.waiting, 0, "failed must not be counted as waiting");
  assert.ok(/failed to sync/.test(s.label), `label should describe a failure, got: ${s.label}`);
  assert.ok(!/waiting to sync/.test(s.label), "failed must not be labelled 'waiting to sync'");
  ok("failed is reported as failed — never 'waiting to sync'");
})();

// `waiting` reflects ONLY pending work.
(() => {
  const s = deriveSyncStatus({ pending: 3, failed: 2 });
  assert.strictEqual(s.waiting, 3, "waiting == pending_count only");
  ok("waiting equals pending_count and excludes failed");
})();

// Convergence requires an ALL-CLEAR queue — the "Last synced just now / 1 failed" combo is impossible.
(() => {
  assert.strictEqual(isFullyConverged({ pending: 0, failed: 0, conflict: 0, locked: 0 }), true);
  assert.strictEqual(isFullyConverged({ pending: 0, failed: 1, conflict: 0, locked: 0 }), false);
  assert.strictEqual(isFullyConverged({ pending: 0, failed: 0, conflict: 1, locked: 0 }), false);
  assert.strictEqual(isFullyConverged({ pending: 0, failed: 0, conflict: 0, locked: 1 }), false);
  assert.strictEqual(isFullyConverged({ pending: 1, failed: 0, conflict: 0, locked: 0 }), false);
  assert.strictEqual(deriveSyncStatus({ failed: 1 }).fully_converged, false);
  ok("fully_converged is true ONLY when no pending/failed/conflict/locked remain");
})();

// Label priority: syncing > conflict > failed > locked > pending > all-synced.
(() => {
  assert.strictEqual(deriveSyncStatus({ pending: 2, failed: 1, conflict: 1 }, { syncing: true }).label, "Synchronizing…");
  assert.ok(/to review/.test(deriveSyncStatus({ failed: 1, conflict: 1, locked: 1 }).label));       // conflict wins
  assert.ok(/failed to sync/.test(deriveSyncStatus({ failed: 1, locked: 1, pending: 1 }).label));    // failed over locked/pending
  assert.ok(/new revision needed/.test(deriveSyncStatus({ locked: 1, pending: 1 }).label));          // locked over pending
  assert.ok(/waiting to sync/.test(deriveSyncStatus({ pending: 1 }).label));
  assert.strictEqual(deriveSyncStatus({}).label, "All changes synced");
  ok("label priority: syncing > conflict > failed > locked > pending > synced");
})();

console.log(`\nsync_status.node.test.js: ${n} checks passed`);
