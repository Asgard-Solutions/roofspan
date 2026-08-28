# Roof Measurement Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:test-driven-development for each behavior and superpowers:verification-before-completion before declaring success.

**Goal:** Close every gap identified in the approved RoofSpan Roof Measurement design while preserving the existing Increment A/B/C architecture.

**Architecture:** Additive measurement facts and derived takeoff-scope totals feed versioned takeoff templates. Field and Office share the same backend model; Field uses its existing durable scoped cache/queue and Relay transport.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, React, Expo React Native, Node contract tests, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-27-roof-measurement-completion-design.md`

## Global constraints

- Do not rewrite Estimate, Assembly, Inventory, Purchasing, ABC Supply, Relay, or mobile sync architecture.
- Keep existing measured-total API semantics backward compatible.
- Never silently recalculate an existing estimate.
- Never hard-code roofing bundle coverage.
- New schema changes are additive.
- Field data must never be dropped merely because Office/Relay is unavailable.

## Task 1 — Add failing backend completion contracts

**Files:**
- Modify: `backend/tests/test_takeoff_core.py`
- Create: `backend/tests/test_measurement_completion_core.py`

**Contracts:**
- scoped physical/takeoff totals preserve excluded structure measurements
- pitch-threshold square metrics use scoped pitch distribution
- stories/height come from included structures
- measured drip edge sits between takeoff override and eave+rake calculation
- product coverage normalizes SF/SQ/EA-style units and falls back safely
- package quantity prefers explicit/product coverage then supplier conversion

Run the targeted pytest contract and confirm the new tests fail for missing behavior.

## Task 2 — Complete measurement persistence and derived totals

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/schemas_measurements.py`
- Modify: `backend/services/measurements.py`
- Create: `backend/services/measurement_core.py`
- Create: `backend/alembic/versions/d9e0f1a2b3c4_measurement_completion.py`

**Behavior:**
- add `MeasurementStructure.included_in_scope` default true
- add `MeasurementSummary.existing_condition`
- add `MeasurementSummary.drip_edge_lf`
- add scoped totals and max stories/height to measurement output
- preserve all new fields across create/replace/clone/revision history
- unassigned geometry remains included

Run targeted measurement/takeoff tests and compile the affected backend modules.

## Task 3 — Complete takeoff interpretation and package math

**Files:**
- Modify: `backend/services/takeoff_core.py`
- Modify: `backend/services/takeoff.py`
- Modify: `backend/takeoff_models.py`
- Modify: `backend/alembic/versions/d9e0f1a2b3c4_measurement_completion.py`
- Modify: `backend/tests/test_takeoff_core.py`

**Behavior:**
- takeoff metrics prefer scoped totals with backward-compatible fallback
- add pitch-threshold metrics and `height_ft`
- resolve drip edge override → measured value → eave+rake
- normalize `Material.coverage_amount/coverage_unit` to line units
- manual rule coverage stays highest priority; supplier conversion remains fallback
- preview/apply expose and persist order quantity coverage provenance
- persist effective waste percent and return prior/current waste impact delta

Run targeted pytest contract and backend compile checks.

## Task 4 — Complete Field offline measurement behavior first with tests

**Files:**
- Create: `mobile/src/measurementCache.js`
- Create: `mobile/src/tests/measurement_cache.node.test.js`
- Modify: `mobile/src/cache.js`
- Modify: `mobile/src/sync.js` only if queue upsert support is required
- Modify: `mobile/src/storage.js` only if durable measurement draft/upsert support is required
- Modify: `mobile/package.json`

**Behavior:**
- online measurement list/detail reads refresh scoped cache
- existing measurements reopen from cache when Office is unreachable
- offline edits immediately update cached detail
- one durable local draft exists per lead/property scope for brand-new unsynced measurement work
- reopening the screen resumes that draft instead of starting blank
- repeated offline saves do not enqueue duplicate create mutations

Run the Node measurement cache contract and existing sync/scope contracts.

## Task 5 — Complete Field UI parity

**Files:**
- Modify: `mobile/src/screens/Measurements.js`

**Behavior:**
- use read-through measurement cache/draft helper
- expose structure inclusion, stories, height, notes
- expose facet width/length/material/notes
- include transition edge
- expose Office penetration types plus optional dimensions/notes
- expose existing condition/underlayment/decking/drip edge/ridge vent
- expose long carry and landscaping protection
- keep fast live totals, photos, incomplete saves, Field Complete and durable queue behavior
- show when cached/offline data is being used

Run mobile Node contracts and Expo/JS syntax/build checks available in CI.

## Task 6 — Complete Office worksheet and takeoff UI

**Files:**
- Modify: `frontend/src/components/MeasurementWorksheet.jsx`
- Modify: `frontend/src/pages/Takeoff.jsx`

**Behavior:**
- worksheet exposes include/exclude, stories/height/attachment/notes
- worksheet exposes facet width/length and complete conditions
- show measured vs takeoff-scoped totals when structures are excluded
- Takeoff metrics include common steep pitch thresholds and height
- preview shows calculated quantity, package/order quantity, coverage source
- preview shows previous vs current effective waste and square impact before apply

Run Office production build.

## Task 7 — Validation and contract CI

**Files:**
- Modify: `backend/services/measurement_validation.py`
- Modify: `backend/tests/test_measurement_validation.py`
- Modify: `.github/workflows/roof-takeoff-contract.yml`

**Behavior:**
- maintain soft-warning behavior
- add scope-specific warnings only where a user action is genuinely needed
- CI runs backend measurement/takeoff contracts, compile checks, mobile measurement/sync contracts, and Office production build on this PR

Run the workflow and fix any failures.

## Task 8 — Full verification and PR

- Run targeted backend contracts.
- Run existing measurement lifecycle/photo/validation tests where CI environment permits.
- Run mobile measurement, sync, scope, photo transport contracts.
- Run Office production build.
- Inspect `main...agent/roof-measurement-full-completion` diff for accidental unrelated changes.
- Open a PR with exact completed behaviors, migration notes, tests, and any environment-only verification caveats.
- Do not merge without explicit user direction.
