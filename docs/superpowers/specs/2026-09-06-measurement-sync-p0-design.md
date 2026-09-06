# RoofSpan Measurement Sync P0 Hardening Design

**Date:** 2026-09-06

## Goal

Correct P0-1 through P0-6 so RoofSpan measurement and roof-sketch changes use a durable transaction boundary, the packaged Windows connector drains the Office outbox, Relay acknowledgements reflect actual cross-node acceptance, mobile conflicts retain a durable merge base, Use Office is generation-safe and atomic, and database constraints match lead-primary measurement identity.

## Scope

This design implements only the six approved P0 findings:

1. Make measurement/sketch mutation, audit entry, and outbox enqueue commit together.
2. Pass the loopback connector token into the packaged Windows `InstallationTunnel` and prove the outbox pump is enabled.
3. Refuse Relay `broadcast_ack` when multi-node publication is not accepted.
4. Persist `base_body` and `base_token` on durable measurement-update mutations and require a valid base before Keep Mine can rebase.
5. Resolve Use Office in one exclusive SQLite transaction guarded by the reviewed mutation generation.
6. Replace global property/inspection uniqueness with hierarchical lead-primary partial indexes in a forward Alembic migration.

No unrelated feature work, UI redesign, or broad audit-service refactor is included.

## Architecture and data flow

### P0-1: PostgreSQL transaction boundary

`log_action()` keeps its current default behavior for existing callers. It gains an explicit non-committing mode used only by measurement and sketch write routes. Those routes stage the business mutation, audit row, and outbox row in one SQLAlchemy session and execute one final `db.commit()`. A rollback/failure-injection test proves that a pre-commit exception persists none of the three.

### P0-2: Packaged connector bootstrap

`RelayWorker` requires `connector_token` from `/api/relay/connector/identity` and supplies it as `outbox_token` to `InstallationTunnel`. Missing tokens are treated as an unhealthy bootstrap and retried; the service must not report a functional tunnel that cannot drain the outbox. Release-contract tests inspect the real worker construction path.

### P0-3: Relay acceptance semantics

`RelayHub.broadcast()` returns an explicit result containing local delivery count and whether the event was accepted for the whole topology. In single-node mode, local completion is accepted. In multi-node mode, shared-transport publication must succeed; publication failure or timeout is not accepted. `installation_ws` sends `broadcast_ack` only for accepted results, leaving the Office row unacknowledged for lease-expiry retry otherwise.

### P0-4: Durable three-way merge base

Every new `measurement_update` mutation stores the authoritative pre-edit document as `base_body` and the corresponding `updated_at` token as `base_token`. Conflict handling uses the durable mutation—not the transient working-draft cache—as the source for Base, Field, and Office. Legacy rows without a trustworthy base cannot execute Keep Mine as a blind full-document overwrite; they remain in review and instruct the rep to use Office and reapply changes.

### P0-5: Atomic, generation-checked Use Office

A new storage transition performs these operations inside `withExclusiveTransactionAsync()`:

- Re-read the reviewed mutation.
- Verify client ID, revision ID, state, and `mutation_generation`.
- Abort as stale if any value changed.
- Delete exactly that conflict/failed row.
- Clear matching saved and working drafts.
- Write the full authoritative Office revision.
- Upsert the scoped revision list.

The screen retains the reviewed mutation generation. Failed-update Use Office fetches the full Office revision before invoking the transition.

### P0-6: Lead-primary database identity

A new forward migration after `d5e6f7a8b9c0` drops the broad property and inspection unique indexes and creates hierarchical partial unique indexes:

- `lead_id` unique whenever non-null.
- `inspection_id` unique only when `lead_id IS NULL`.
- `property_id` unique only when both `lead_id IS NULL` and `inspection_id IS NULL`.

The migration reports historical sets whose relationships indicate prior cross-lead merging, but it does not split data without provable lineage. Tests cover distinct leads on the same property.

## Compatibility and error handling

- Existing `log_action()` callers continue committing by default.
- Existing measurement mutations without `base_body` remain readable and recoverable but cannot use blind Keep Mine.
- Relay publication exceptions are contained at the WebSocket loop and intentionally leave the durable Office event eligible for retry.
- A missing connector token causes bounded connector retry, not a false-ready data path.
- Migration downgrade restores the prior broad indexes only after verifying that the database satisfies them; downgrade failure is preferable to silent data merging.

## Verification

Each P0 is implemented test-first and committed separately. The final gate includes focused backend, Relay, Windows release-contract, mobile Node, migration-graph, Office build, and mobile bundle workflows. GitHub Actions are the authoritative full-repository execution environment because the current tool sandbox cannot clone external repositories.