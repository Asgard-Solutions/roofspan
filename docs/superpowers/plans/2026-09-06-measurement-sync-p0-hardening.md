# RoofSpan Measurement Sync P0 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct P0-1 through P0-6 so measurement and roof-sketch synchronization is transactionally durable, connector-driven, topology-safe, conflict-safe, and aligned with lead-primary database identity.

**Architecture:** Keep the current authoritative Office/PostgreSQL and offline-first Field design. Harden the existing transaction, Relay, Windows bootstrap, mobile queue, SQLite transition, and Alembic boundaries without introducing a parallel sync system.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic, WebSockets, Valkey/Redis Pub/Sub, React Native/Expo 54, JavaScript/CommonJS Node contract tests, expo-sqlite, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-06-measurement-sync-p0-design.md`

## Global Constraints

- Implement P0-1 through P0-6 in that order.
- Write a regression test first and confirm the expected failure before production code for each P0.
- Preserve `log_action()` default commit behavior for unrelated callers.
- Never acknowledge an Office outbox event unless the Relay accepted responsibility for the full configured topology.
- Never resolve Keep Mine without a durable, trustworthy base document.
- Never discard a newer mutation generation from an older Use Office review.
- Add a forward Alembic migration; do not rely on editing an already-applied migration.
- Keep every P0 independently reviewable and committed.

---

### Task 1: P0-1 — Single PostgreSQL transaction for business write, audit, and outbox

**Files:**
- Modify: `backend/core.py`
- Modify: `backend/routers/measurements.py`
- Modify: `backend/routers/measurement_sketches.py`
- Create: `backend/tests/test_measurement_outbox_transaction.py`

**Interfaces:**
- Produces: `log_action(..., commit: bool = True)`; measurement/sketch routes call it with `commit=False` before `office_outbox.emit_for_revision()` and one final `db.commit()`.

- [ ] Add tests proving `commit=False` stages an audit row without committing and a forced rollback persists neither the measurement mutation, audit row, nor outbox row.
- [ ] Run the focused test on the unmodified implementation and confirm failure because `log_action()` commits.
- [ ] Add the optional `commit` parameter; use `await db.flush()` when false and retain the existing default commit when true.
- [ ] Update every Office measurement and Office roof-sketch write route that emits an outbox event to use the non-committing audit path.
- [ ] Run the focused test, existing outbox tests, measurement lifecycle tests, and migration graph checks.
- [ ] Commit as `fix: make measurement outbox writes transactional`.

### Task 2: P0-2 — Enable the packaged Windows connector outbox pump

**Files:**
- Modify: `windows/winbuild/relay_entry.py`
- Modify: `windows/tests/test_relay_connector_release_contract.py`
- Create: `windows/tests/test_relay_connector_outbox_bootstrap.py`

**Interfaces:**
- Consumes: identity response key `connector_token`.
- Produces: `InstallationTunnel(..., outbox_token=connector_token)` from the actual `RelayWorker` bootstrap path.

- [ ] Add a source-contract test and runtime worker test proving the token is required and passed to `InstallationTunnel`.
- [ ] Run the tests before production changes and confirm failure.
- [ ] Parse and validate `connector_token` in `RelayWorker`; missing token enters the existing bounded retry path.
- [ ] Pass the token as `outbox_token`.
- [ ] Run Windows connector release-contract and bootstrap tests.
- [ ] Commit as `fix: start relay connector outbox pump`.

### Task 3: P0-3 — Acknowledge Relay broadcasts only after topology acceptance

**Files:**
- Modify: `backend/relay/hub.py`
- Modify: `backend/relay/server.py`
- Modify: `backend/tests/test_relay_broadcast.py`
- Modify: `backend/tests/integration/test_relay_broadcast_e2e.py`

**Interfaces:**
- Produces: `BroadcastResult(delivered_local: int, accepted: bool)` from `RelayHub.broadcast()`.
- `installation_ws` sends `broadcast_ack` only when `accepted` is true.

- [ ] Add tests for publish exception, publish timeout/cancellation-safe behavior, local delivery plus failed cross-node publish, and no acknowledgment on rejection.
- [ ] Run the tests against current code and confirm failure because publish errors are swallowed and callers receive an unconditional success path.
- [ ] Implement the explicit result contract; single-node mode is accepted after local processing, multi-node mode requires successful transport publication.
- [ ] Update `installation_ws` to omit `broadcast_ack` on rejected publication and leave the connector lease to expire.
- [ ] Run Relay unit tests and the Valkey integration test.
- [ ] Commit as `fix: gate relay acknowledgements on broadcast acceptance`.

### Task 4: P0-4 — Persist and use a durable three-way-merge base

**Files:**
- Modify: `mobile/src/queue.js`
- Modify: `mobile/src/screens/Measurements.js`
- Modify: `mobile/src/sync.js`
- Modify: `mobile/src/measurementReconcile.js`
- Modify: `mobile/src/tests/measurement_three_way_merge.node.test.js`
- Modify: `mobile/src/tests/measurement_acceptance.node.test.js`

**Interfaces:**
- Produces durable mutation fields `base_body` and `base_token` for `measurement_update`.
- Produces a conflict merge decision that refuses Keep Mine for legacy rows without a valid base.

- [ ] Add a test that models save clearing the working draft, Office changing one group, Field changing another group, and conflict resolution preserving both.
- [ ] Add a legacy-row test proving Keep Mine is blocked when `base_body` is absent.
- [ ] Run tests and confirm failure because the durable row lacks the base.
- [ ] Extend mutation creation to accept and persist the base fields.
- [ ] Stage measurement updates with the complete authoritative pre-edit document and token before sealing the working draft.
- [ ] Resolve Base/Field/Office from the durable conflict mutation rather than the working-draft cache.
- [ ] Run all mobile measurement Node contracts and Expo Babel parsing.
- [ ] Commit as `fix: persist measurement conflict merge base`.

### Task 5: P0-5 — Make Use Office generation-safe and SQLite-atomic

**Files:**
- Create: `mobile/src/measurementConflict.js`
- Modify: `mobile/src/storage.js`
- Modify: `mobile/src/sync.js`
- Modify: `mobile/src/screens/Measurements.js`
- Create: `mobile/src/tests/measurement_conflict_transition.node.test.js`
- Modify: `mobile/package.json`

**Interfaces:**
- Produces: `buildMeasurementConflictReview(...)` and `applyMeasurementResolutionInTx(...)` pure decision/transition contract.
- Produces: `resolveMeasurementConflictTransition(reviewed)` storage API using `withExclusiveTransactionAsync()`.

- [ ] Add pure transition tests for exact-generation success, stale-generation rejection, wrong revision/state rejection, full Office adoption, and rollback propagation.
- [ ] Add a screen/runtime contract test proving the reviewed mutation carries `client_id` and `mutation_generation` and failed-update recovery fetches the full Office revision.
- [ ] Run tests and confirm failure because no atomic transition exists.
- [ ] Implement the pure transition helper.
- [ ] Implement one exclusive SQLite transaction that re-reads and verifies the mutation, deletes only the reviewed generation, clears matching drafts, writes the full Office detail, and upserts the scoped list.
- [ ] Wire conflict and failed-update UI paths to the atomic API; return `stale` without modifying storage when a newer generation exists.
- [ ] Run all measurement contracts and Expo bundle parsing.
- [ ] Commit as `fix: make measurement use-office atomic`.

### Task 6: P0-6 — Align database constraints with lead-primary identity

**Files:**
- Create: `backend/alembic/versions/e7f8a9b0c1d2_lead_primary_measurement_sets.py`
- Modify: `backend/tests/test_measurement_lead_primary_iter92.py`
- Create: `backend/tests/test_measurement_set_constraint_migration.py`

**Interfaces:**
- Produces hierarchical partial indexes:
  - `uq_measurement_sets_lead` where `lead_id IS NOT NULL`.
  - `uq_measurement_sets_inspection_fallback` where `lead_id IS NULL AND inspection_id IS NOT NULL`.
  - `uq_measurement_sets_property_fallback` where `lead_id IS NULL AND inspection_id IS NULL AND property_id IS NOT NULL`.

- [ ] Add migration tests proving two distinct leads may own separate measurement sets for the same property while duplicate lead IDs remain prohibited.
- [ ] Add a migration-source assertion for report-only detection of suspicious historical cross-lead relationships.
- [ ] Run tests and confirm failure under the broad property uniqueness index.
- [ ] Add the forward migration after `d5e6f7a8b9c0`; drop the old property/inspection indexes and create the hierarchical indexes without splitting historical data.
- [ ] Make downgrade explicitly validate broad uniqueness before recreating the old indexes.
- [ ] Run Alembic graph validation, migration upgrade/downgrade tests, and measurement lead-primary tests.
- [ ] Commit as `fix: align measurement set constraints with lead identity`.

### Task 7: Final integration and merge

**Files:**
- Modify only if required by failures in the six scoped areas.

- [ ] Run focused backend, Relay, Windows, mobile measurement, roof-sketch, migration, Office-build, and production Metro bundle workflows.
- [ ] Review the complete branch diff against the design and confirm no unrelated behavior changes.
- [ ] Open a pull request to `main` with test evidence and migration/rollout notes.
- [ ] Wait for all required GitHub Actions checks to complete.
- [ ] Correct any scoped regression, rerun checks, and merge only when the branch is green.
