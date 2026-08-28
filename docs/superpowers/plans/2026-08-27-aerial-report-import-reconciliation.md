# RoofSpan Aerial/Report Import and Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Office-only import subsystem that safely ingests EagleView, HOVER, GAF QuickMeasure, and generic report bundles; preserves original artifacts; produces field/item confidence-scored normalized proposals; reconciles them against the current RoofSpan measurement/sketch; and creates a new draft revision only after explicit user confirmation.

**Architecture:** Build a provider-adapter pipeline behind one normalized proposal contract. Original files are stored locally and fingerprinted before parsing; structured provider formats are preferred over PDF inference. Import proposals are persisted separately from `MeasurementRevision`, so they cannot affect takeoff/estimates until reconciliation is resolved and `apply` creates a new revision. Import artifacts are included in a matched backup/restore set so database restores never strand report metadata from its source files.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL JSONB, `defusedxml`, `pypdf`, `ezdxf`, Python stdlib `json/csv/zipfile/hashlib`, React 19/CRA, shared `@roofspan/roof-sketch-core`, existing local backup/off-site copy services.

**Spec:** `docs/superpowers/specs/2026-08-27-roof-sketch-aerial-import-design.md`

**Dependency:** Implement `docs/superpowers/plans/2026-08-27-roof-sketch-implementation.md` first. This plan consumes `MeasurementSketchDocument`, the sketch API, and `@roofspan/roof-sketch-core`.

## Global Constraints

- Imports run only in RoofSpan Office; Field never parses report files.
- Original source files stay local; no third-party upload is introduced.
- Supported first-class providers: EagleView, HOVER, GAF QuickMeasure.
- Generic fallback supports safe attempts for PDF, XML, JSON, CSV, DXF, and ESX.
- Structured provider data outranks PDF extraction when schemas are recognized.
- Confidence is field/item specific: High, Medium, Low with deterministic reasons.
- `Accept All High-Confidence` accepts High only; Medium/Low remain unresolved.
- Existing measurement revisions are never overwritten by an import.
- Applying an import creates the next draft revision and preserves prior revision facts unchanged.
- A parse failure, malformed file, unsupported format, or unresolved required conflict cannot create a revision.
- No automatic takeoff/estimate recalculation.
- Original file + SHA-256 + parser/provider metadata + reconciliation decisions + accepting user/timestamp are retained for audit.
- Import artifact files must participate in backup/restore/off-site copy as a matched set with the PostgreSQL dump.

---

## File Structure

Persistence and source-file storage:

- `backend/measurement_import_models.py` — `MeasurementImport`, `MeasurementImportFile`, `MeasurementRevisionProvenance`.
- `backend/alembic/versions/f1a2b3c4d5e6_measurement_imports.py` — additive migration after sketch migration `e0f1a2b3c4d5`.
- `backend/services/measurement_import_storage.py` — safe local path, atomic write/read, checksums, bundle limits.
- `backend/schemas_measurement_imports.py` — API/proposal/confidence/reconciliation envelopes.

Parsing framework:

- `backend/integrations/measurements/__init__.py`
- `backend/integrations/measurements/contracts.py` — adapter interface + normalized proposal shapes.
- `backend/integrations/measurements/security.py` — MIME/header/size/archive validation.
- `backend/integrations/measurements/detect.py` — provider/format detection and adapter selection.
- `backend/integrations/measurements/generic.py` — conservative JSON/XML/CSV/PDF/DXF/ESX fallback.
- `backend/integrations/measurements/hover.py` — HOVER adapter.
- `backend/integrations/measurements/gaf_quickmeasure.py` — GAF QuickMeasure adapter.
- `backend/integrations/measurements/eagleview.py` — EagleView adapter.
- `backend/services/measurement_imports.py` — orchestrate parse/normalize/validate/score/state transitions.
- `backend/services/measurement_reconciliation.py` — deterministic diff/decision/apply logic.

API/UI:

- `backend/routers/measurement_imports.py` — Office-only import/upload/parse/reconcile/apply endpoints.
- `backend/server.py` — register router.
- `frontend/src/components/measurement-import/ImportMeasurementDialog.jsx` — upload/detection stage.
- `frontend/src/components/measurement-import/ImportSummary.jsx` — provider/validation/confidence summary.
- `frontend/src/components/measurement-import/ReconciliationWorkspace.jsx` — layered reconciliation.
- `frontend/src/components/measurement-import/ReconciliationTable.jsx` — section/item decisions.
- `frontend/src/components/measurement-import/SketchDiffOverlay.jsx` — current/imported sketch comparison using existing sketch renderer.
- `frontend/src/components/measurement-import/importApi.js` — API adapter.
- `frontend/src/components/MeasurementWorksheet.jsx` — `Import Measurement Report` action and post-apply refresh.

Backup/restore:

- `backend/services/backup_artifacts.py` — deterministic import-artifact ZIP + manifest create/verify/restore.
- `backend/services/backup.py` — create/copy/prune matched DB + artifact + manifest set.
- `backend/routers/admin_ops.py` — restore/upload/list matched set behavior where current backup routes require extension.
- `backend/tests/test_backup_import_artifacts.py` — matched-set backup/restore contract.

Fixtures/tests:

- `backend/tests/fixtures/measurement_imports/hover/` — sanitized provider-shaped JSON/XML/PDF samples.
- `backend/tests/fixtures/measurement_imports/gaf/` — sanitized provider-shaped XML/DXF/PDF samples.
- `backend/tests/fixtures/measurement_imports/eagleview/` — sanitized provider-shaped JSON/XML/DXF/PDF samples.
- `backend/tests/fixtures/measurement_imports/generic/` — generic JSON/XML/CSV/DXF/PDF/invalid files.
- `backend/tests/test_measurement_import_security.py`
- `backend/tests/test_measurement_import_generic.py`
- `backend/tests/test_measurement_import_providers.py`
- `backend/tests/test_measurement_reconciliation.py`
- `backend/tests/test_measurement_import_api.py`

CI:

- `.github/workflows/roof-takeoff-contract.yml` — import/parser/reconciliation/backup contract coverage.

---

### Task 1: Add import persistence and safe local artifact storage

**Files:**
- Create: `backend/measurement_import_models.py`
- Create: `backend/alembic/versions/f1a2b3c4d5e6_measurement_imports.py`
- Create: `backend/schemas_measurement_imports.py`
- Create: `backend/services/measurement_import_storage.py`
- Test: `backend/tests/test_measurement_import_security.py`

**Interfaces:**
- `store_import_file(import_id, original_filename, data, media_type) -> StoredImportFile`
- `read_import_file(relative_path) -> bytes`
- `sha256_bytes(data) -> str`
- `MeasurementImport.status`: `received|parsing|review_required|ready|applied|failed`.

- [ ] **Step 1: Write failing storage/security tests**

Cover exact cases:

```python
def test_filename_is_sanitized_and_cannot_escape_import_root(): ...
def test_sha256_is_stable_for_same_bytes(): ...
def test_atomic_write_returns_relative_path_only(): ...
def test_duplicate_checksum_is_detected_for_same_measurement_set(): ...
def test_oversized_bundle_is_rejected_before_parser_runs(): ...
```

Use configured constants in the service: maximum 50 MiB per file, 150 MiB per bundle, 20 files per bundle.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_security.py
```

- [ ] **Step 3: Add migration/models**

Migration revision is exactly `f1a2b3c4d5e6`, `down_revision = "e0f1a2b3c4d5"`.

`measurement_imports` includes IDs/scope/provider/report/parser/status/proposal/confidence/validation/reconciliation/created revision/user/timestamps/errors.

`measurement_import_files` includes import FK, filename, media type, format, role, relative path, SHA-256, size, timestamp, with index on SHA-256.

`measurement_revision_provenance` is one row per revision with JSONB `values` keyed by stable structure/facet/edge/penetration IDs.

- [ ] **Step 4: Implement local import root and atomic storage**

Resolve root in this order:
1. `ROOFSPAN_IMPORT_STORAGE_DIR` if set;
2. `<ROOFSPAN_DATA_ROOT>/measurement-imports`;
3. Windows `C:\ProgramData\RoofSpan\measurement-imports`;
4. dev fallback under backend data.

Never trust the original filename as a path. Store as `imports/<import_uuid>/<file_uuid>.<safe_extension>` and keep original filename only as metadata.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_security.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/measurement_import_models.py backend/alembic/versions/f1a2b3c4d5e6_measurement_imports.py backend/schemas_measurement_imports.py backend/services/measurement_import_storage.py backend/tests/test_measurement_import_security.py
git commit -m "feat: add measurement import persistence"
```

---

### Task 2: Build the normalized adapter contract and conservative generic parsers

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/integrations/measurements/__init__.py`
- Create: `backend/integrations/measurements/contracts.py`
- Create: `backend/integrations/measurements/security.py`
- Create: `backend/integrations/measurements/detect.py`
- Create: `backend/integrations/measurements/generic.py`
- Create: `backend/tests/fixtures/measurement_imports/generic/*`
- Test: `backend/tests/test_measurement_import_generic.py`

**Interfaces:**
- `detect_bundle(files) -> Detection(provider, formats, adapter_name, confidence, reasons)`.
- Every adapter implements `detect(files)`, `parse(files)`, `normalize(native)`, `validate(proposal)`, `score(proposal)`.
- `NormalizedProposal` has `structures`, `facets`, `edges`, `penetrations`, `summary`, `sketches`, `reported_totals`, `field_confidence`, `validation`.

- [ ] **Step 1: Add parser dependencies**

Add pinned dependencies using versions selected by a fresh dependency resolution compatible with Python 3.12, then freeze exact versions in `backend/requirements.txt`:

```text
defusedxml
pypdf
ezDXF
```

Do not add OCR or AI parsing dependencies in this release.

- [ ] **Step 2: Write failing generic parser tests**

Fixtures must cover: recognized JSON object, safe XML, CSV totals, simple ASCII DXF lines/polylines, text PDF containing roof totals, image-only PDF returning `review_required`, malicious XML entity blocked, nested/unsafe ESX archive blocked, unknown schema remaining Low confidence.

- [ ] **Step 3: Implement adapter dataclasses/protocol**

Example normalized field result:

```python
{
  "path": "facets.F1.area_sqft",
  "value": 515.0,
  "unit": "sqft",
  "source_file_id": "...",
  "provider_native_ref": "RF-1",
  "confidence": "low",
  "reason": "generic_pdf_table",
}
```

Confidence reasons are machine-readable strings, not free-form-only text.

- [ ] **Step 4: Implement security-first generic parsing**

Order: JSON/XML/CSV structured parse → PDF embedded text/tables → DXF deterministic geometry → ESX safe-container inspection. Generic PDF diagram reconstruction remains Low and must not fabricate facet-edge relationships when labels cannot be proved.

- [ ] **Step 5: Run generic/security tests**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_generic.py backend/tests/test_measurement_import_security.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/integrations/measurements backend/tests/fixtures/measurement_imports/generic backend/tests/test_measurement_import_generic.py
git commit -m "feat: add measurement import adapter framework"
```

---

### Task 3: Implement HOVER, GAF QuickMeasure, and EagleView adapters with golden fixtures

**Files:**
- Create: `backend/integrations/measurements/hover.py`
- Create: `backend/integrations/measurements/gaf_quickmeasure.py`
- Create: `backend/integrations/measurements/eagleview.py`
- Create: `backend/tests/fixtures/measurement_imports/hover/*`
- Create: `backend/tests/fixtures/measurement_imports/gaf/*`
- Create: `backend/tests/fixtures/measurement_imports/eagleview/*`
- Test: `backend/tests/test_measurement_import_providers.py`

**Interfaces:**
- Known-provider adapters return High only for recognized fields that pass schema/unit/cross-check rules.
- HOVER supports recognized `measurements.json` / `roof_lines` / XML 3D export and accompanying PDF/ESX where supplied.
- GAF supports QuickMeasure XML/DXF/PDF bundle.
- EagleView supports recognized measurement JSON/XML/DXF/PDF bundle artifacts.

- [ ] **Step 1: Create sanitized golden fixtures**

Each provider fixture set contains at minimum:
- one structured measurement file;
- one geometry file where provider output exposes geometry;
- one PDF reference fixture;
- one deliberately altered/conflicting value fixture.

Fixtures must contain no real customer names/addresses. Keep provider field names/shape necessary for parser regression.

- [ ] **Step 2: Write failing adapter tests**

For each provider assert: detection, report ID, facet labels, pitch normalization (`"8/12" -> 8.0`), total area, edge mapping, geometry scale when proven, structured-vs-PDF preference, and contradiction producing unresolved conflict rather than silent selection.

- [ ] **Step 3: Implement HOVER adapter**

Map HOVER roof facets/roof pitch/roof measurements/roof-line geometry into canonical proposal. Recognized full/summarized JSON and XML fields may reach High when units/schema are known and totals cross-check; PDF-only association remains Medium/Low based on certainty.

- [ ] **Step 4: Implement GAF QuickMeasure adapter**

Use XML for structured facts and DXF for geometry where available; retain PDF as reference/cross-check. Do not assume a PDF value identifies a specific facet unless the recognized template provides the relationship.

- [ ] **Step 5: Implement EagleView adapter**

Prefer recognized JSON/XML measurement output; use DXF for sketch geometry where deterministic; retain PDF for reference. Unknown EagleView export versions fail into `review_required` rather than being treated as known High-confidence schema.

- [ ] **Step 6: Run provider tests**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_providers.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/measurements/hover.py backend/integrations/measurements/gaf_quickmeasure.py backend/integrations/measurements/eagleview.py backend/tests/fixtures/measurement_imports backend/tests/test_measurement_import_providers.py
git commit -m "feat: add aerial measurement provider adapters"
```

---

### Task 4: Implement confidence scoring, layered reconciliation, and safe apply core

**Files:**
- Create: `backend/services/measurement_imports.py`
- Create: `backend/services/measurement_reconciliation.py`
- Modify: `backend/services/measurements.py`
- Test: `backend/tests/test_measurement_reconciliation.py`

**Interfaces:**
- `parse_import(db, import_id, user) -> MeasurementImport`.
- `build_reconciliation(current_revision, proposal) -> ReconciliationDocument`.
- `apply_decisions(reconciliation, decisions) -> ResolvedMeasurementDraft`.
- `create_revision_from_import(db, import_id, user) -> MeasurementRevision`.

- [ ] **Step 1: Write failing reconciliation tests**

Cover:

```python
async def test_accept_all_high_never_accepts_medium_or_low(...): ...
async def test_keep_current_preserves_current_facet_value(...): ...
async def test_edit_proposed_uses_user_value_and_records_provenance(...): ...
async def test_unresolved_required_conflict_blocks_apply(...): ...
async def test_apply_creates_next_revision_without_mutating_prior(...): ...
async def test_apply_does_not_recalculate_takeoff(...): ...
```

Also compare structures, facets, edges, penetrations, summary conditions, and sketch object IDs.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_reconciliation.py
```

- [ ] **Step 3: Implement deterministic confidence rules**

High requires recognized provider schema + known units + validation success + no contradictory bundle source. Medium handles reliable provider PDF extraction/incomplete context/non-critical mismatch. Low handles generic inference, ambiguous associations, unknown schema, reconstructed diagram, or conflicts.

- [ ] **Step 4: Implement layered decision document**

Decision states are exactly: `unresolved`, `accept_imported`, `keep_current`, `edited`. Bulk high acceptance changes only items with `confidence == "high"` and no blocking validation error.

- [ ] **Step 5: Implement apply transaction**

Inside one DB transaction:
1. lock/reload import and current revision;
2. verify import is `ready` and unresolved required count is zero;
3. clone/create next revision using existing revision service;
4. replace accepted relational facts in the new draft only;
5. create canonical sketch documents from resolved imported/current geometry;
6. persist provenance JSON keyed by stable logical IDs;
7. mark import `applied` and link `created_revision_id`;
8. write audit events;
9. commit.

On exception rollback all DB changes; original file remains intact and import remains reviewable/failed as appropriate.

- [ ] **Step 6: Run reconciliation + measurement/takeoff regressions**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_reconciliation.py backend/tests/test_measurement_completion_core.py backend/tests/test_takeoff_core.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/measurement_imports.py backend/services/measurement_reconciliation.py backend/services/measurements.py backend/tests/test_measurement_reconciliation.py
git commit -m "feat: add measurement import reconciliation core"
```

---

### Task 5: Add Office import/reconciliation API

**Files:**
- Create: `backend/routers/measurement_imports.py`
- Modify: `backend/server.py`
- Test: `backend/tests/test_measurement_import_api.py`

**Interfaces:**
- `POST /api/measurement-imports` — create import tied to measurement set/property/inspection.
- `POST /api/measurement-imports/{id}/files` — multipart upload, one file per call.
- `POST /api/measurement-imports/{id}/parse` — detect/parse/normalize/score.
- `GET /api/measurement-imports/{id}` — proposal/status/validation/confidence.
- `PUT /api/measurement-imports/{id}/reconciliation` — persist decision document.
- `POST /api/measurement-imports/{id}/apply` — create new draft revision.
- Owner/Admin/Office only.

- [ ] **Step 1: Write failing API tests**

Test Office role success, Sales rejection, duplicate checksum response, malformed file parse failure with no revision, parse-to-review state, persistence of decisions, unresolved apply 409, successful apply 201/new revision, idempotent second apply returns same created revision rather than another one.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_api.py
```

- [ ] **Step 3: Implement router with readable errors**

Parser exceptions map to stable codes such as `unsupported_format`, `invalid_file`, `unsafe_archive`, `parser_failed`, `provider_version_unknown`, `reconciliation_incomplete`. Never expose filesystem paths or raw stack traces to UI.

- [ ] **Step 4: Register router and audit events**

Audit actions:

```text
measurement_import.create
measurement_import.file_added
measurement_import.parsed
measurement_import.reconciliation_saved
measurement_import.applied
measurement_import.failed
```

- [ ] **Step 5: Run API + full import core tests**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_measurement_import_api.py backend/tests/test_measurement_import_security.py backend/tests/test_measurement_import_generic.py backend/tests/test_measurement_import_providers.py backend/tests/test_measurement_reconciliation.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/measurement_imports.py backend/server.py backend/tests/test_measurement_import_api.py
git commit -m "feat: expose measurement report import API"
```

---

### Task 6: Build Office upload, confidence summary, layered reconciliation, and sketch overlay UI

**Files:**
- Create: `frontend/src/components/measurement-import/importApi.js`
- Create: `frontend/src/components/measurement-import/ImportMeasurementDialog.jsx`
- Create: `frontend/src/components/measurement-import/ImportSummary.jsx`
- Create: `frontend/src/components/measurement-import/ReconciliationTable.jsx`
- Create: `frontend/src/components/measurement-import/SketchDiffOverlay.jsx`
- Create: `frontend/src/components/measurement-import/ReconciliationWorkspace.jsx`
- Modify: `frontend/src/components/MeasurementWorksheet.jsx`

**Interfaces:**
- `ReconciliationWorkspace({importId, currentRevision, onApplied, onClose})`.
- Reuse the sketch canvas/geometry package from the first plan; do not implement a second drawing engine.

- [ ] **Step 1: Add `Import Measurement Report` action**

Show action only to owner/administrator/office. File picker permits `.pdf,.xml,.json,.csv,.dxf,.esx` and multiple selection. Upload each file, then explicitly start Parse.

- [ ] **Step 2: Implement detection/validation summary**

Show provider, detected formats, report ID, parser version, source files/checksum abbreviated, status, and High/Medium/Low counts. Parse failure remains on this screen with source artifact retained.

- [ ] **Step 3: Implement layered reconciliation table**

Top totals followed by expandable Structures → Facets → Edges → Penetrations → Conditions. Every row displays Current, Imported, Difference, Confidence, Reason, and action. Provide `Accept All High-Confidence`, `Accept Section`, `Keep Current Section`, per-item `Accept Imported`, `Keep Current`, `Edit Proposed`.

- [ ] **Step 4: Implement synchronized sketch overlay**

Render current and proposed sketch documents in one viewport. Selecting a table row selects the matching geometry; selecting geometry focuses the matching row. Distinguish unchanged, changed, imported-new, missing/removed, unresolved through renderer state/classes without encoding business meaning only by color; include labels/icons/stroke patterns.

- [ ] **Step 5: Gate Create Measurement Revision**

Disable button while required unresolved count > 0 with explanatory text. On apply, show returned revision number and refresh `MeasurementWorksheet` to the new draft. Do not invoke Takeoff preview/apply automatically.

- [ ] **Step 6: Build Office**

```bash
cd frontend
yarn build
```

Expected: successful production build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/measurement-import frontend/src/components/MeasurementWorksheet.jsx
git commit -m "feat: add measurement import reconciliation workspace"
```

---

### Task 7: Extend backup/restore/off-site copy to include original import artifacts

**Files:**
- Create: `backend/services/backup_artifacts.py`
- Modify: `backend/services/backup.py`
- Modify: `backend/routers/admin_ops.py`
- Test: `backend/tests/test_backup_import_artifacts.py`

**Interfaces:**
- For timestamp `T`, matched set names:
  - `roofspan_T.dump`
  - `roofspan_T.artifacts.zip`
  - `roofspan_T.manifest.json`
- Manifest contains SHA-256/size of dump + artifact ZIP and archive schema version.

- [ ] **Step 1: Write failing backup artifact tests**

Cover: archive includes measurement-import files; manifest hashes verify; corrupted ZIP/hash blocks restore; missing artifact ZIP blocks restore when manifest says artifacts exist; safe extraction blocks traversal; off-site copy transfers all matched files; retention prunes sets, never individual members.

- [ ] **Step 2: Run tests and confirm failure**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_backup_import_artifacts.py
```

- [ ] **Step 3: Implement deterministic artifact archive**

Archive only the RoofSpan-managed `measurement-imports` storage root. Store relative paths. Write ZIP to `.partial`, fsync/close, then atomically replace. Manifest is written only after dump and ZIP both exist and hashes are computed.

- [ ] **Step 4: Modify backup creation/list/copy/prune**

A backup is considered complete only when its manifest validates. Existing pre-feature `.dump` files remain listable/restorable as legacy DB-only backups. New off-site copy copies manifest + dump + artifacts ZIP and writes the `.offsite` marker only after all members succeed.

- [ ] **Step 5: Modify restore**

For matched-set backups: validate hashes before changing the live DB; stage artifact extraction in a temporary directory; take existing safety backup; restore DB; atomically swap import artifact directory; if artifact swap fails after DB restore, surface restore failure and preserve staged/current files for recovery instead of deleting evidence.

- [ ] **Step 6: Run backup regressions**

```bash
PYTHONPATH=backend pytest -q backend/tests/test_backup_import_artifacts.py backend/tests/test_backup_pg_tools.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/backup_artifacts.py backend/services/backup.py backend/routers/admin_ops.py backend/tests/test_backup_import_artifacts.py
git commit -m "feat: back up measurement import artifacts"
```

---

### Task 8: Expand CI and execute end-to-end import/reconciliation verification

**Files:**
- Modify: `.github/workflows/roof-takeoff-contract.yml`
- Modify/Test: only import/sketch/backup files from this and the dependency plan.

**Interfaces:**
- CI asserts migration head `f1a2b3c4d5e6` and executes parser/security/reconciliation/backup tests plus Office build and existing measurement/photo contracts.

- [ ] **Step 1: Expand workflow paths and install test parser dependencies**

Include `backend/integrations/measurements/**`, import models/services/router/schemas/tests/fixtures, backup artifact files, frontend measurement-import components, and migration `f1a2b3c4d5e6`.

The backend contract job must install the exact pinned `defusedxml`, `pypdf`, and `ezdxf` versions from `backend/requirements.txt` needed by these tests.

- [ ] **Step 2: Run the deterministic import suite in CI**

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_measurement_import_security.py \
  backend/tests/test_measurement_import_generic.py \
  backend/tests/test_measurement_import_providers.py \
  backend/tests/test_measurement_reconciliation.py \
  backend/tests/test_measurement_import_api.py \
  backend/tests/test_backup_import_artifacts.py \
  backend/tests/test_measurement_sketch_service.py \
  backend/tests/test_measurement_sketch_api.py \
  backend/tests/test_measurement_completion_core.py \
  backend/tests/test_takeoff_core.py
```

- [ ] **Step 3: Update Alembic contract**

Assert exactly one head and it starts with `f1a2b3c4d5e6`.

- [ ] **Step 4: Build Office and run existing Field/photo contracts**

```bash
cd frontend && yarn install --frozen-lockfile && yarn build
cd ../mobile && npm ci && npm run test:measurements && npm run test:sync
```

Existing photo-sync contract must remain green; this feature must not alter photo queue transport behavior.

- [ ] **Step 5: Manual end-to-end acceptance using fixture bundles**

Verify all four flows against a local Office build:
1. HOVER structured bundle → parse → Accept All High → resolve remaining → new draft revision.
2. GAF XML/DXF/PDF bundle → geometry overlay → per-edge conflict decision → new draft revision.
3. EagleView structured bundle → current-vs-import comparison → prior revision remains unchanged.
4. Generic PDF with ambiguous geometry → Low/Review Required → cannot apply until unresolved items are explicitly resolved or kept current.

Then verify no estimate/takeoff changed until the user explicitly runs existing recalculation.

- [ ] **Step 6: Commit CI changes**

```bash
git add .github/workflows/roof-takeoff-contract.yml
git commit -m "ci: enforce measurement import contracts"
```

---

## Plan Self-Review Checklist

- Spec coverage: Office-only importing, provider adapters, generic fallback, original artifacts/checksum, confidence, layered reconciliation, overlay, new-revision apply, provenance, parser/security failure handling, and artifact-aware backup/restore all have tasks.
- Placeholder scan: no TBD/TODO implementation placeholders remain.
- Type consistency: one import proposal uses `NormalizedProposal`; one decision state set is `unresolved|accept_imported|keep_current|edited`; one applied import links exactly one `created_revision_id`.
- Safety boundary: parser/adapter output never writes measurement revisions directly; only reconciliation apply may create a revision.
- Provider drift: unrecognized schema versions degrade to Review Required/Unsupported, never automatic High confidence.
- Backup boundary: new backups after this feature are matched sets; legacy DB-only dumps remain backward compatible.
