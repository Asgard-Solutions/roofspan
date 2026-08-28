# RoofSpan 2D Roof Sketch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one canonical 2D roof sketch model that RoofSpan Office and RoofSpan Field can both create/edit, with connected-graph drawing, manual polygons, hybrid scale/calibration, locked measured edges, explicit measurement-proposal acceptance, offline durability, and structure-level conflict handling.

**Architecture:** Introduce a shared pure-JavaScript `roof-sketch-core` package for geometry/topology/proposal math, then persist one versioned sketch JSON document per measurement revision + structure in PostgreSQL. Office renders the document with SVG; Field renders the same document with React Native SVG and stores pending edits in the existing offline cache/mutation queue. Relational measurement facets/edges/penetrations remain authoritative; sketch-derived values stay proposals until explicitly accepted.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL JSONB, React 19/CRA, Expo SDK 54/React Native 0.81, React Native SVG, Node 22 tests, existing Relay/offline queue.

**Spec:** `docs/superpowers/specs/2026-08-27-roof-sketch-aerial-import-design.md`

## Global Constraints

- `MeasurementRevision` remains the only estimate-driving measurement record.
- Verified/locked revisions are immutable; corrections create a new revision.
- Connected graph is the default edit mode; manual polygons are also supported.
- Geometry-derived area/length/orientation values are proposals until explicitly accepted.
- A locked measured edge is more authoritative than calculated geometry.
- Unscaled geometry is visual-only and must not produce dimensional proposals.
- Office and Field must use the same geometry/math implementation.
- Field remains offline-first and must survive restart/crash/Relay outage without losing the latest unsynced sketch.
- Structure-level optimistic concurrency must reject same-structure stale writes; never use last-write-wins.
- Existing photo-sync behavior and current measurement/takeoff semantics must remain green.
- No automatic takeoff/estimate recalculation is introduced.

---

## File Structure

Create a reusable package rather than duplicating math in Office and Field:

- `packages/roof-sketch-core/package.json` — local package metadata/CommonJS entrypoint.
- `packages/roof-sketch-core/index.js` — public API only.
- `packages/roof-sketch-core/schema.js` — canonical document creation/normalization/version rules.
- `packages/roof-sketch-core/geometry.js` — distance, polygon area, pitch-adjusted area, calibration.
- `packages/roof-sketch-core/topology.js` — edge loops, shared-edge checks, self-intersection/gap/overlap validation.
- `packages/roof-sketch-core/proposals.js` — deterministic proposal generation and confirmed-vs-proposed comparisons.
- `packages/roof-sketch-core/test/roofSketchCore.node.test.js` — pure deterministic contract tests.

Backend sketch persistence/API:

- `backend/measurement_sketch_models.py` — `MeasurementSketchDocument` ORM model.
- `backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py` — additive migration after `d9e0f1a2b3c4`.
- `backend/schemas_sketch.py` — Pydantic read/write envelopes.
- `backend/services/measurement_sketches.py` — immutable-revision checks, versioned save/load/clone logic.
- `backend/routers/measurement_sketches.py` — Office sketch endpoints.
- `backend/routers/mobile.py` — salesperson-scoped mobile sketch endpoints using the same service.
- `backend/services/measurements.py` — clone revision copies sketch docs; facet geometry projection stays synchronized on accepted proposals.
- `backend/server.py` — include the new Office sketch router.
- `backend/tests/test_measurement_sketch_service.py` — service/version/clone tests.
- `backend/tests/test_measurement_sketch_api.py` — Office/mobile API/authorization/conflict tests.

Office UI:

- `frontend/package.json`, `frontend/yarn.lock` — local `roof-sketch-core` dependency.
- `frontend/src/components/roof-sketch/RoofSketchEditor.jsx` — editor state/commands/undo-redo.
- `frontend/src/components/roof-sketch/RoofSketchCanvas.jsx` — SVG renderer + pointer interaction.
- `frontend/src/components/roof-sketch/SketchInspector.jsx` — edge/facet/pitch/calibration/lock controls.
- `frontend/src/components/roof-sketch/ProposalPanel.jsx` — Accept Proposed / Keep Current controls.
- `frontend/src/components/roof-sketch/sketchApi.js` — Office sketch API adapter.
- `frontend/src/components/MeasurementWorksheet.jsx` — Sketch Roof entry point and refresh after accepted changes.

Field UI/offline:

- `mobile/package.json`, `mobile/package-lock.json` — local `roof-sketch-core` and Expo-compatible `react-native-svg`.
- `mobile/src/sketchCache.js` — deterministic cache/draft/mutation keys.
- `mobile/src/cache.js` — read-through sketch cache facade.
- `mobile/src/queue.js` — deterministic `measurement_sketch_update` identity.
- `mobile/src/screens/RoofSketch.js` — touch-first sketch editor shell.
- `mobile/src/components/RoofSketchCanvas.js` — React Native SVG renderer/gestures.
- `mobile/src/components/SketchInspector.js` — touch controls for type/pitch/calibration/locks/proposals.
- `mobile/src/screens/Measurements.js` — navigation into current structure sketch.
- `mobile/App.js` — register `RoofSketch` in both lead and map stacks.
- `mobile/src/tests/sketch_cache.node.test.js` — offline identity/coalescing tests.

CI:

- `.github/workflows/roof-takeoff-contract.yml` — expand path filters/tests/build parsing for sketch modules and new migration head.

---

### Task 1: Build the shared canonical sketch/geometry package

**Files:**
- Create: `packages/roof-sketch-core/package.json`
- Create: `packages/roof-sketch-core/index.js`
- Create: `packages/roof-sketch-core/schema.js`
- Create: `packages/roof-sketch-core/geometry.js`
- Create: `packages/roof-sketch-core/topology.js`
- Create: `packages/roof-sketch-core/proposals.js`
- Create: `packages/roof-sketch-core/test/roofSketchCore.node.test.js`

**Interfaces:**
- Produces: `createSketchDocument`, `normalizeSketchDocument`, `distance`, `calibrateScale`, `polygonArea`, `pitchAdjustedArea`, `validateSketch`, `deriveProposals`, `compareProposal`.
- Consumed by: Office editor, Field editor, import/reconciliation plan.

- [ ] **Step 1: Write failing pure Node tests for canonical math and safety**

Use fixtures with exact known results:

```js
const {
  createSketchDocument, calibrateScale, polygonArea, pitchAdjustedArea,
  validateSketch, deriveProposals,
} = require("..");

assert.equal(polygonArea([[0,0],[10,0],[10,8],[0,8]]), 80);
assert.equal(Math.round(pitchAdjustedArea(80, 6) * 1000) / 1000, 89.443);

const scale = calibrateScale({ canvasDistance: 10, realFeet: 25 });
assert.equal(scale.feetPerUnit, 2.5);

const doc = createSketchDocument({ structureId: "s1" });
assert.equal(doc.schema_version, 1);
assert.equal(doc.edit_mode, "connected_graph");
```

Also test: shared edge referenced by two facets; self-intersection blocked; zero-length edge blocked; unresolved scale suppresses LF/SF proposal; locked measured edge stays confirmed even when geometry disagrees.

- [ ] **Step 2: Run the package tests and confirm failure**

Run:

```bash
node packages/roof-sketch-core/test/roofSketchCore.node.test.js
```

Expected: FAIL because the package/functions do not exist yet.

- [ ] **Step 3: Implement the minimal canonical package**

`package.json` must expose CommonJS so both Metro and plain Node can consume it:

```json
{
  "name": "@roofspan/roof-sketch-core",
  "version": "1.0.0",
  "private": true,
  "main": "index.js"
}
```

Use one document schema with `schema_version: 1`, `edit_mode`, `vertices`, `edges`, `facets`, `penetrations`, `scale`, `proposal_decisions`, and `validation`.

Pitch-adjusted area must use:

```js
function pitchAdjustedArea(planArea, pitchRise) {
  const rise = Number(pitchRise);
  return Number(planArea) * Math.sqrt(1 + Math.pow(rise / 12, 2));
}
```

`deriveProposals()` must return no dimensional proposal when scale is unresolved and must emit discrepancies rather than overwrite locked dimensions.

- [ ] **Step 4: Run tests to green**

Run:

```bash
node packages/roof-sketch-core/test/roofSketchCore.node.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/roof-sketch-core
git commit -m "feat: add shared roof sketch geometry core"
```

---

### Task 2: Add versioned sketch persistence and clone semantics

**Files:**
- Create: `backend/measurement_sketch_models.py`
- Create: `backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py`
- Create: `backend/schemas_sketch.py`
- Create: `backend/services/measurement_sketches.py`
- Modify: `backend/services/measurements.py`
- Test: `backend/tests/test_measurement_sketch_service.py`

**Interfaces:**
- Produces: `get_sketch(db, revision_id, structure_id)`, `list_sketches(...)`, `save_sketch(..., expected_version)`, `clone_sketches(db, from_revision_id, to_revision_id, structure_id_map)`.
- Save returns `{document_version, document, updated_at}`.

- [ ] **Step 1: Write failing service tests**

Cover:

```python
async def test_new_sketch_starts_at_version_one(db, draft_revision, structure): ...
async def test_stale_sketch_version_raises_conflict(db, draft_revision, structure): ...
async def test_locked_revision_cannot_be_modified(db, locked_revision, structure): ...
async def test_clone_revision_copies_sketch_and_remaps_structure(db, ...): ...
```

Assert same `(revision_id, structure_id)` is unique and stale `expected_version=1` fails after server reaches version 2.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_service.py
```

Expected: import/model failures.

- [ ] **Step 3: Add the additive migration and ORM model**

Create table `measurement_sketch_documents` with:

```python
id UUID primary key
revision_id UUID FK measurement_revisions.id ON DELETE CASCADE
structure_id UUID FK measurement_structures.id ON DELETE CASCADE
schema_version Integer not null default 1
document_version Integer not null default 1
edit_mode String(24) not null default 'connected_graph'
document JSONB not null default '{}'
created_by String(255)
updated_by String(255)
created_at DateTime(timezone=True)
updated_at DateTime(timezone=True)
UniqueConstraint('revision_id','structure_id', name='uq_measurement_sketch_revision_structure')
```

Migration revision is exactly `e0f1a2b3c4d5`, `down_revision = "d9e0f1a2b3c4"`.

- [ ] **Step 4: Implement service version checks and clone behavior**

`save_sketch()` must:
1. verify revision exists and `editable` semantics allow mutation;
2. verify structure belongs to revision;
3. compare client `expected_version` to current `document_version`;
4. on mismatch raise a typed conflict carrying the current server document;
5. update/increment atomically;
6. never mutate relational measurement values automatically.

Extend `clone_revision()` to call `clone_sketches()` after child structures/facets have been recreated and IDs remapped.

- [ ] **Step 5: Run service + existing measurement tests**

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_measurement_sketch_service.py \
  backend/tests/test_measurement_completion_core.py \
  backend/tests/test_measurement_validation.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/measurement_sketch_models.py backend/alembic/versions/e0f1a2b3c4d5_measurement_sketches.py backend/schemas_sketch.py backend/services/measurement_sketches.py backend/services/measurements.py backend/tests/test_measurement_sketch_service.py
git commit -m "feat: persist versioned roof sketch documents"
```

---

### Task 3: Expose Office and Field sketch APIs with conflict payloads

**Files:**
- Create: `backend/routers/measurement_sketches.py`
- Modify: `backend/routers/mobile.py`
- Modify: `backend/server.py`
- Test: `backend/tests/test_measurement_sketch_api.py`

**Interfaces:**
- Office:
  - `GET /api/measurements/{revision_id}/sketches`
  - `GET /api/measurements/{revision_id}/sketches/{structure_id}`
  - `PUT /api/measurements/{revision_id}/sketches/{structure_id}`
- Field mirrors under `/api/mobile/measurements/{revision_id}/sketches/...` with existing salesperson scope enforcement.
- PUT request: `{schema_version, edit_mode, document, expected_version}`.
- Stale PUT: HTTP 409 `{detail:{message, server:{...current sketch...}}}`.

- [ ] **Step 1: Write failing API tests**

Test owner/office read-write, salesperson scoped access, unauthorized cross-rep rejection, immutable revision rejection, stale version 409, and different-structure concurrent saves succeeding independently.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_api.py
```

- [ ] **Step 3: Implement Office router and register it**

Use existing `require_roles(*FIELD_ROLES)` for editable measurement users and existing measurement immutability/service checks; write audit actions:

```text
measurement.sketch.create
measurement.sketch.update
measurement.sketch.conflict
```

- [ ] **Step 4: Add Field routes to `routers/mobile.py`**

Reuse `_assert_measurement_scope`; do not introduce a separate mobile persistence path.

- [ ] **Step 5: Run API + mobile authorization regressions**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_api.py backend/tests/test_mobile_api.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/measurement_sketches.py backend/routers/mobile.py backend/server.py backend/tests/test_measurement_sketch_api.py
git commit -m "feat: add office and field roof sketch APIs"
```

---

### Task 4: Build the Office SVG sketch editor and explicit proposal workflow

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/yarn.lock`
- Create: `frontend/src/components/roof-sketch/sketchApi.js`
- Create: `frontend/src/components/roof-sketch/RoofSketchCanvas.jsx`
- Create: `frontend/src/components/roof-sketch/SketchInspector.jsx`
- Create: `frontend/src/components/roof-sketch/ProposalPanel.jsx`
- Create: `frontend/src/components/roof-sketch/RoofSketchEditor.jsx`
- Modify: `frontend/src/components/MeasurementWorksheet.jsx`

**Interfaces:**
- `RoofSketchEditor({revision, structure, facets, edges, penetrations, onMeasurementChanged, onClose})`.
- Uses `@roofspan/roof-sketch-core` only for geometry/math; renderer contains no duplicate area/scale formula.

- [ ] **Step 1: Add local package dependency and install**

In `frontend/package.json` add:

```json
"@roofspan/roof-sketch-core": "file:../packages/roof-sketch-core"
```

Run:

```bash
cd frontend
yarn install
```

- [ ] **Step 2: Implement editor command state with undo/redo**

Represent every edit as a document replacement produced from commands such as `addVertex`, `moveVertex`, `addEdge`, `splitEdge`, `setEdgeType`, `setFacetPitch`, `setScale`, `lockEdge`, `placePenetration`. Keep capped in-memory history (100 states) and persist only the current document.

- [ ] **Step 3: Implement SVG interaction**

Required behaviors: zoom/pan, vertex drag, vertex/edge snapping, add/split/join/delete edges, facet labels, dimension labels, connected graph default, manual polygon toggle, penetration placement, validation markers.

- [ ] **Step 4: Implement hybrid calibration and locked dimensions**

Calibration flow: select edge/segment → enter known feet → call shared `calibrateScale()` → preview recalculated proposals. Lock flow stores `confirmed_length_ft` and `locked: true`; moving geometry may show a discrepancy but may not change the confirmed LF.

- [ ] **Step 5: Implement proposal panel**

For each changed facet/edge show:

```text
F3 confirmed: 412 SF
Sketch proposes: 428 SF (+16 SF)
[Accept Proposed] [Keep Current]
```

`Accept Proposed` updates the editable worksheet fact and records the decision in `proposal_decisions`; `Keep Current` records the rejection while preserving the existing fact. Never call takeoff recalculation.

- [ ] **Step 6: Wire `Sketch Roof` into `MeasurementWorksheet.jsx`**

Each structure gets a sketch entry point; immutable revisions offer the existing `New revision` flow before editing. Closing after accepted proposal refreshes worksheet state without losing unrelated unsaved values.

- [ ] **Step 7: Build Office UI**

```bash
cd frontend
yarn build
```

Expected: successful production build.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/yarn.lock frontend/src/components/roof-sketch frontend/src/components/MeasurementWorksheet.jsx
git commit -m "feat: add office roof sketch editor"
```

---

### Task 5: Add Field sketch cache, mutation identity, and conflict durability

**Files:**
- Modify: `mobile/package.json`
- Modify: `mobile/package-lock.json`
- Create: `mobile/src/sketchCache.js`
- Modify: `mobile/src/cache.js`
- Modify: `mobile/src/queue.js`
- Create: `mobile/src/tests/sketch_cache.node.test.js`
- Modify: `mobile/src/tests/measurement_cache.node.test.js`

**Interfaces:**
- `sketchDetailKey(revisionId, structureId)` → stable cache key.
- `sketchDraftKey(revisionId, structureId)` → stable unsynced draft key.
- `sketchUpdateMutationId(revisionId, structureId)` → `measurement-sketch-update:<revision>:<structure>`.

- [ ] **Step 1: Write failing Node tests**

Assert repeated offline edits of one structure reuse the same mutation ID, while two different structures have different IDs. Assert draft round-trip preserves `document_version`, local document, and base server document needed for conflict review.

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd mobile
node src/tests/sketch_cache.node.test.js
```

- [ ] **Step 3: Add dependencies**

```bash
cd mobile
npm install ../packages/roof-sketch-core
npx expo install react-native-svg
```

Commit both `package.json` and `package-lock.json`.

- [ ] **Step 4: Implement cache/read-through helpers**

`cache.sketch(revisionId, structureId)` calls `/mobile/measurements/{revision}/sketches/{structure}` and falls back to the latest local sketch. Local saves happen before queueing so process death after a user edit cannot erase it.

- [ ] **Step 5: Extend queue deterministic identity**

Add a `_measurementSketchUpdateId(kind, path)` branch for `kind === "measurement_sketch_update"`. Existing photo and measurement identities must remain unchanged.

- [ ] **Step 6: Run offline queue regressions**

```bash
cd mobile
npm run test:measurements
node src/tests/sketch_cache.node.test.js
npm run test:sync
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mobile/package.json mobile/package-lock.json mobile/src/sketchCache.js mobile/src/cache.js mobile/src/queue.js mobile/src/tests/sketch_cache.node.test.js mobile/src/tests/measurement_cache.node.test.js
git commit -m "feat: add offline roof sketch sync foundation"
```

---

### Task 6: Build the Field touch sketch editor and crash recovery

**Files:**
- Create: `mobile/src/components/RoofSketchCanvas.js`
- Create: `mobile/src/components/SketchInspector.js`
- Create: `mobile/src/screens/RoofSketch.js`
- Modify: `mobile/src/screens/Measurements.js`
- Modify: `mobile/App.js`

**Interfaces:**
- Screen params: `{revision_id, structure_id, structure_name}`.
- Saves one complete structure sketch document with `expected_version` and queue kind `measurement_sketch_update`.

- [ ] **Step 1: Register the new screen in both measurement-capable stacks**

Import `RoofSketch` and add a `RoofSketch` screen immediately after `Measurements` in `MapStack` and `LeadStack`.

- [ ] **Step 2: Implement touch renderer**

Use React Native SVG for paths/polygons/labels and React Native gestures/touch handlers for drag, pinch zoom, and pan. All geometry calculations call `@roofspan/roof-sketch-core`.

- [ ] **Step 3: Implement Field controls**

Support connected graph, manual polygon mode, edge classification, facet pitch, calibration, measured-and-locked edge entry, penetration positioning, undo/redo, proposal Accept/Keep controls, and validation messages.

- [ ] **Step 4: Implement autosave-to-local-draft before queued network save**

After every committed command, debounce local SQLite cache persistence. Explicit Save writes the latest document to cache first and then queues the deterministic mutation with the server `document_version` as the optimistic token.

- [ ] **Step 5: Implement 409 conflict screen state**

When queue state is `conflict`, show server vs local metadata and three safe actions: use server copy, preserve local copy by starting/continuing a new editable revision, or manually reconcile. Never automatically merge graph JSON.

- [ ] **Step 6: Wire structure buttons from `Measurements.js`**

Each structure card gets `Sketch roof`. Existing cached/offline measurement detail provides the revision/structure IDs; local unsynced brand-new measurement drafts must show `Save measurement first to create a revision before sketching` rather than inventing a server revision ID.

- [ ] **Step 7: Parse and test Field modules**

```bash
cd mobile
npm run test:measurements
node src/tests/sketch_cache.node.test.js
node -e "const b=require('@babel/core'); ['src/screens/RoofSketch.js','src/components/RoofSketchCanvas.js','src/components/SketchInspector.js'].forEach(f=>b.transformFileSync(f,{presets:['babel-preset-expo']})); console.log('Field sketch parsed')"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add mobile/App.js mobile/src/screens/Measurements.js mobile/src/screens/RoofSketch.js mobile/src/components/RoofSketchCanvas.js mobile/src/components/SketchInspector.js
git commit -m "feat: add field roof sketch editor"
```

---

### Task 7: Expand CI contract and perform full sketch verification

**Files:**
- Modify: `.github/workflows/roof-takeoff-contract.yml`
- Modify/Test as needed: only files from Tasks 1–6.

**Interfaces:**
- CI becomes the release contract for the new migration head, shared core, backend APIs, Field offline tests, and Office build.

- [ ] **Step 1: Extend workflow path filters**

Include `packages/roof-sketch-core/**`, `backend/measurement_sketch_models.py`, sketch schemas/services/router/tests, migration `e0f1a2b3c4d5`, Office roof-sketch components, Field sketch modules, and mobile package lock.

- [ ] **Step 2: Update backend contract job**

Run:

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_measurement_sketch_service.py \
  backend/tests/test_measurement_sketch_api.py \
  backend/tests/test_measurement_completion_core.py \
  backend/tests/test_measurement_validation.py \
  backend/tests/test_takeoff_core.py
```

Alembic graph assertion must find exactly one head and match `e0f1a2b3c4d5`.

- [ ] **Step 3: Add shared-core and Field contract steps**

```bash
node packages/roof-sketch-core/test/roofSketchCore.node.test.js
cd mobile && npm run test:measurements && node src/tests/sketch_cache.node.test.js
```

Also Babel-parse the three new Field sketch modules.

- [ ] **Step 4: Run Office production build**

```bash
cd frontend
yarn install --frozen-lockfile
yarn build
```

- [ ] **Step 5: Run the full local verification set before completion**

```bash
node packages/roof-sketch-core/test/roofSketchCore.node.test.js
PYTHONPATH=backend pytest -q backend/tests/test_measurement_sketch_service.py backend/tests/test_measurement_sketch_api.py backend/tests/test_measurement_completion_core.py backend/tests/test_measurement_validation.py backend/tests/test_takeoff_core.py
cd mobile && npm run test:measurements && node src/tests/sketch_cache.node.test.js && npm run test:sync
cd ../frontend && yarn build
```

Expected: all tests/builds green. Also explicitly verify the existing photo-sync contract workflow remains green before claiming completion.

- [ ] **Step 6: Commit CI changes**

```bash
git add .github/workflows/roof-takeoff-contract.yml
git commit -m "ci: enforce roof sketch contracts"
```

---

## Plan Self-Review Checklist

- Spec coverage: shared canonical model, connected/manual modes, calibration, locked edges, proposals, Office, Field, offline recovery, optimistic conflicts, immutable revisions, no auto-takeoff are all assigned to tasks.
- Placeholder scan: no TBD/TODO/future implementation steps remain in this plan.
- Type consistency: one structure sketch key is `(revision_id, structure_id)`; one optimistic token is `document_version`; mobile deterministic mutation identity is `measurement-sketch-update:<revision>:<structure>`.
- Dependency boundary: import/provider parsing is intentionally excluded and implemented by the second plan; it consumes the sketch core/API produced here.
