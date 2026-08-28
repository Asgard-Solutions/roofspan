# RoofSpan 2D Roof Sketch and Aerial/Report Import Design

**Date:** 2026-08-27  
**Status:** Approved in design review; self-reviewed; pending written-spec review before implementation planning

## Goal

Extend the completed RoofSpan measurement subsystem with two tightly coupled capabilities:

1. A shared **2D roof facet sketch/editor** available in RoofSpan Office and RoofSpan Field.
2. A local Office-only **aerial/report import pipeline** that can normalize structured provider data and PDFs into the same RoofSpan measurement/sketch model.

The new work must preserve the existing workflow and authority chain:

**Property → Inspection → Measurement Set → Measurement Revision → Takeoff → Estimate → Quote → Job → Material Order**

A `MeasurementRevision` remains the only estimate-driving measurement record. A sketch or import proposal may calculate or suggest values, but it must never silently replace confirmed physical measurements or mutate a verified/locked revision.

## Locked product decisions

The following decisions were approved during design review and are requirements for this implementation:

- 2D sketch editing is supported in **both Office and Field**.
- The sketch is **hybrid with confirmation**: geometry may propose area/length values, but confirmed measurement values change only after explicit user acceptance.
- Roof drawing supports **both connected-graph and manual-polygon editing**, with connected graph as the default.
- Scaling uses a **hybrid calibration model**: structure-level calibration, provider-native scale, and individually locked measured edges.
- Imported files may be **structured reports and PDFs**.
- First-class provider adapters are implemented for **EagleView, HOVER, and GAF QuickMeasure**, with a generic fallback importer for other supported files.
- Importing is **Office only**. Field receives the resulting sketch/revision through the normal RoofSpan sync model.
- Imports use **confidence-based review**. Nothing creates an estimate-driving revision until the user explicitly confirms the proposal.
- Original import files are retained locally with **SHA-256 checksum, parser metadata, provider metadata, source filename, timestamps, confidence results, and audit history**.
- Importing into a property that already has measurements creates a **new proposed revision workflow**. The existing revision is never overwritten.
- Reconciliation is **layered**: `Accept All High-Confidence`, section-level controls, and item-level drill-down.

## Architectural boundaries

### Existing measurement model remains authoritative

The current measurement model already provides the correct foundation:

- `MeasurementRevision` is snapshot/version based.
- `MeasurementStructure` represents physical roof structures.
- `MeasurementFacet` already has a `geometry` JSON field reserved for sketch/aerial compatibility.
- `MeasurementEdge` stores individual classified edge segments and can reference one or two facets for shared hips/valleys.
- `MeasurementPenetration` stores physical roof penetrations.
- Existing derived totals and takeoff-scoped totals remain unchanged in meaning.
- Verified/locked revisions are immutable; corrections create a new revision.

This design extends that model. It does not create a parallel measurement system.

### Local-first architecture remains unchanged

- Local PostgreSQL remains the authoritative business store.
- RoofSpan Office performs report parsing locally.
- RoofSpan Field remains offline-first and communicates through the existing Relay architecture.
- No direct operational cloud database is introduced.
- Report files are not uploaded to a third-party service as part of this feature.

### No silent recalculation downstream

A sketch edit or report import must not automatically recalculate an estimate, quote, job, or material order. Existing takeoff/recalculation rules remain explicit.

If a newer measurement revision exists, downstream work surfaces that fact using the current measurement/takeoff provenance behavior.

## 2D sketch architecture

### One canonical sketch model

Manual drawing, Field drawing, Office drawing, EagleView imports, HOVER imports, GAF QuickMeasure imports, DXF geometry, and generic report parsing all normalize into one canonical RoofSpan sketch representation.

There must not be provider-specific sketch objects or separate Office/Field geometry formats.

### Sketch document granularity

Add the required `MeasurementSketchDocument` model and store one **revision-scoped sketch document per structure**.

`MeasurementSketchDocument`

- `id`
- `revision_id`
- `structure_id`
- `schema_version`
- `edit_mode` (`connected_graph` | `manual_polygon`)
- `document_version`
- `document` JSONB
- `created_by`
- `created_at`
- `updated_by`
- `updated_at`

A structure-level document is intentional:

- it keeps graph geometry atomic;
- it supports Field whole-document offline persistence;
- it allows structure-level optimistic concurrency;
- it avoids thousands of database rows for transient drawing vertices;
- it provides a clean unit for import comparison and conflict resolution.

The `document` JSON contains vertices, edges, facet loops, positioned penetrations, scale/calibration metadata, provenance, validation state, and unresolved/accepted/kept-current geometry proposal state.

### Canonical coordinate system

The sketch is a **2D plan-view representation**.

The document stores floating-point local X/Y coordinates in canvas units plus explicit scale metadata. Coordinates are not assumed to be feet until scale is resolved.

Each sketch document includes:

- local coordinate system identifier/version;
- bounds/viewport metadata;
- optional north/azimuth rotation;
- scale status (`unresolved` | `calibrated` | `provider_native`);
- scale conversion to feet;
- calibration provenance.

Provider 3D geometry must be normalized to a 2D plan projection before entering the canonical sketch model. Provider-reported roof-surface area remains a separate proposed measurement fact and must not be overwritten merely because a projected polygon can be drawn.

### Vertices

Each vertex contains:

- stable UUID/client ID;
- X/Y coordinate;
- source/provenance (`manual`, `field`, `office`, `imported`);
- optional constraint metadata;
- optional confidence metadata for imported geometry.

### Edges

Each sketch edge contains:

- stable UUID/client ID;
- start vertex ID;
- end vertex ID;
- edge classification: `eave`, `rake`, `ridge`, `hip`, `valley`, `sidewall`, `headwall`, `transition`;
- primary facet reference;
- optional secondary facet reference;
- calculated plan length;
- calculated real-world length when scale is resolved;
- optional confirmed/locked measured length;
- provenance/confidence;
- validation state.

Shared roof lines are represented by one edge referenced by both adjacent facets. Moving a ridge, hip, or valley therefore updates both neighboring facets from the same geometry.

### Facets

Each sketch facet contains:

- stable sketch ID;
- existing RoofSpan facet/client ID mapping;
- existing RoofSpan facet label such as `F1`;
- ordered edge-loop references and direction;
- pitch rise over 12;
- orientation/azimuth when known;
- calculated projected area;
- calculated pitch-adjusted roof-surface area when valid;
- current confirmed `MeasurementFacet.area_sqft` for comparison;
- source/provenance/confidence;
- validation state.

The canonical sketch must preserve the existing facet identity. `F1` in the worksheet is the same logical facet shown as `F1` in the sketch.

### Connected graph and manual polygon modes

Both modes use the same document schema.

**Connected graph mode** is the default and enforces shared vertices/edges between adjacent facets.

**Manual polygon mode** allows independent facet boundaries for complex roofs, unusual additions, and import cleanup. It relaxes shared-topology requirements but still uses vertices, edges, and facet loops from the same canonical model.

Manual mode must still validate:

- self-intersections;
- impossible polygons;
- excessive gaps;
- excessive overlaps;
- unscaled geometry;
- duplicate/zero-length edges.

### Penetrations

The sketch can position penetrations as a point or footprint associated with an existing measurement penetration.

Each positioned penetration contains:

- measurement penetration ID/client ID;
- facet reference;
- X/Y position or footprint;
- penetration type;
- dimensions when present;
- provenance/confidence.

The relational `MeasurementPenetration` record remains authoritative for type, quantity, and confirmed dimensions.

## Scale and dimension rules

### Structure-level calibration

A user may calibrate a structure by selecting a known segment and entering its real measured distance. RoofSpan derives a structure scale from that calibration.

### Provider-native scale

A structured import may provide coordinate units or enough geometry metadata to establish scale without manual calibration. The provider adapter must record why that scale is trusted.

### Locked measured edges

A user may mark a specific edge **Measured & Locked** and enter a field-measured length.

A locked measured edge is more authoritative than a geometry-calculated value.

Editing geometry may change the calculated length, but it must not silently change the confirmed locked measurement. The UI instead shows the discrepancy and requires the user to explicitly unlock or replace the confirmed measurement.

### Scale precedence

For dimension proposals, use this conceptual authority order:

1. explicitly locked measured edge/dimension;
2. trusted provider-native dimension accepted by the user;
3. calibrated geometry calculation;
4. unscaled geometry — visual only, no dimensional proposal.

## Geometry-derived measurement proposals

The sketch is not automatically authoritative for measurements.

When scale and topology are valid, the geometry engine may calculate proposals for:

- facet projected area;
- facet roof-surface area from pitch;
- edge lengths;
- orientation;
- geometry-based validation totals.

For a plan-view facet with known pitch, roof-surface area may be derived from projected area and pitch. The implementation must use one tested canonical formula shared by Office and Field.

Calculated values are stored/displayed as **proposals** until accepted.

Example UI behavior:

`F3 confirmed area: 412 SF`  
`Sketch proposal: 428 SF (+16 SF)`

Actions:

- `Accept Proposed`
- `Keep Current`

Accepting a value updates the draft measurement fact through the normal revision workflow and records provenance. Keeping the current value preserves the existing confirmed fact.

Proposal decisions are persisted in the structure sketch document so unresolved/accepted/kept-current state survives navigation, Office restart, Field app restart, and offline recovery.

## Shared geometry engine

Implement the geometry rules as a shared, deterministic JavaScript module that can be consumed by both Office and Field.

The shared engine owns:

- polygon area;
- pitch-adjusted area;
- distance calculations;
- calibration/scale;
- snapping math;
- shared-edge topology;
- facet-loop validation;
- overlap/gap detection;
- self-intersection detection;
- dimension constraints;
- derived proposal generation;
- import geometry normalization helpers;
- deterministic comparison helpers.

Office and Field must not implement separate area/length math.

## Office sketch editor

Office uses a desktop-focused 2D renderer, preferably browser-native SVG or an equally lightweight vector renderer that does not duplicate the geometry engine.

Required interactions:

- zoom/pan;
- add/move/delete vertices;
- add/split/join/delete edges;
- snap to vertices/edges;
- classify roof lines;
- create/delete facets;
- connected graph default mode;
- manual polygon mode;
- assign pitch;
- assign orientation;
- show facet labels;
- show dimension labels;
- calibrate scale;
- mark dimension `Measured & Locked`;
- place/move penetrations;
- undo/redo;
- validation/warning display;
- proposal comparison and acceptance.

Keyboard/mouse affordances should favor precision without changing the underlying document format.

## Field sketch editor

Field supports the same sketch data and measurement semantics with touch-first controls.

Required Field capabilities:

- create/edit connected roof graph;
- manual polygon mode;
- pinch zoom/pan;
- add/move vertices;
- classify edges;
- assign facets/pitch;
- calibrate scale;
- enter and lock measured edge lengths;
- place penetrations;
- view calculated proposals;
- accept/keep proposed values;
- undo/redo during the current editing session;
- persist unsynced sketch state across app restart/crash.

Field does not import or parse aerial/report files.

## Offline and concurrency behavior

### Field persistence

Sketch documents participate in the existing scoped Field cache and durable mutation queue.

Each structure sketch has a stable local identity and deterministic mutation identity. Repeated offline edits to the same structure update/coalesce the latest sketch mutation rather than enqueueing stale copies of the whole edit history.

The latest unsynced document must be restored after:

- app restart;
- process crash;
- loss of connectivity;
- Relay outage.

### Structure-level optimistic concurrency

Use a structure-level `document_version` / ETag-style token for sketch writes.

If Office and Field edit different structures, they can sync independently.

If both modify the same structure from the same base version, RoofSpan must not use last-write-wins. It returns a conflict containing the latest server sketch and local pending sketch.

Conflict handling allows:

- choose latest Office/server version;
- preserve the local version as the basis of a new draft revision where existing revision rules allow it;
- manually reconcile the structure.

RoofSpan must not automatically merge two independently modified roof graphs for the same structure.

## Import architecture

### Office-only local import subsystem

All parsing happens in RoofSpan Office.

Import sequence:

**Select File(s) → Fingerprint/Security Validation → Detect Provider/Format → Parse Native Data → Normalize → Validate/Cross-check → Score Confidence → Build Import Proposal → Reconcile → Create New Draft Revision**

An import proposal is not a `MeasurementRevision` and cannot drive takeoff/estimate calculations.

### Import bundles

Allow the user to select multiple related files as one report bundle.

Examples:

- provider PDF + XML;
- PDF + XML + DXF;
- HOVER JSON + PDF;
- provider structured file plus diagram file.

RoofSpan groups the files into one `MeasurementImport` and cross-checks the data sources.

When multiple files describe the same value:

- structured provider data is preferred over PDF text extraction when the schema is recognized;
- geometry-specific structured data/DXF may be preferred for sketch shape;
- PDF is retained as the human-readable reference;
- contradictions are surfaced as reconciliation conflicts rather than silently resolved.

## Provider adapters

Each adapter implements the same contract:

- `detect(files)` — identify provider, report ID, format/version, and detection confidence;
- `parse(files)` — extract provider-native facts without rewriting meaning;
- `normalize(native)` — map into RoofSpan's canonical import proposal;
- `validate(proposal)` — validate units, totals, geometry, topology, and required relationships;
- `score(proposal)` — assign field/item confidence with reasons.

### EagleView adapter

First-class support targets provider-delivered measurement artifacts that contain enough structured information to map roof facts/sketch geometry, including PDF, XML, JSON, and DXF when available.

The adapter prefers structured data when present and retains the PDF for audit/reference.

### HOVER adapter

First-class support targets HOVER JSON measurements/roof-line data, XML exports, PDFs, DXF, and ESX when those files are supplied.

HOVER's structured JSON/XML artifacts are preferred for measurement facts and normalized geometry because they are intended for external-system integration.

### GAF QuickMeasure adapter

First-class support targets GAF QuickMeasure PDF, XML, and DXF report files.

The XML/DXF sources are preferred for structured facts/geometry where reliable, with the PDF retained for visual cross-checking.

### Generic fallback adapter

The generic importer may accept supported file types such as:

- PDF;
- XML;
- JSON;
- CSV;
- DXF;
- ESX.

Generic parsing must be conservative. Unknown schemas do not receive provider-trust confidence simply because they are parseable.

Image-only/scanned PDFs may be retained and surfaced for manual review even when RoofSpan cannot safely infer reliable roof geometry. The first release must prefer safe incompleteness over fabricated measurements.

## PDF parsing rules

Use a conservative parsing order:

1. embedded text/table extraction;
2. recognized provider template extraction;
3. embedded/vector drawing extraction where deterministic;
4. generic diagram inference only as a low-confidence fallback.

A PDF may produce high-confidence totals without producing high-confidence facet-to-edge geometry. Confidence is assigned at the field/item level.

No inferred value becomes High confidence solely because a generic parser generated it.

## Import persistence and audit

### Measurement import record

Add the required `MeasurementImport` model.

`MeasurementImport`

- `id`
- `measurement_set_id`
- `property_id`
- `inspection_id`
- `provider`
- `provider_report_id`
- `detected_format/version`
- `parser_name`
- `parser_version`
- `status` (`received`, `parsing`, `review_required`, `ready`, `applied`, `failed`)
- `normalized_proposal` JSONB
- `confidence_summary` JSONB
- `validation_results` JSONB
- `reconciliation_decisions` JSONB
- `created_revision_id` nullable
- `created_by`
- `created_at`
- `completed_at`
- `error_code`
- `error_message`

### Import source files

Add the required `MeasurementImportFile` model.

`MeasurementImportFile`

- `id`
- `import_id`
- `original_filename`
- `media_type`
- `file_format`
- `file_role`
- `storage_relative_path`
- `sha256`
- `size_bytes`
- `created_at`

Original report bytes are stored on local durable application storage, not as PostgreSQL blobs.

Self-hosted path resolution follows the existing `ROOFSPAN_DATA_ROOT` pattern:

- when `ROOFSPAN_DATA_ROOT` is set: `<ROOFSPAN_DATA_ROOT>/measurement_imports`;
- Windows default: `%ProgramData%\RoofSpan\measurement_imports`;
- development/non-Windows fallback: a persistent backend data directory consistent with existing local object-storage behavior.

Only relative artifact paths are stored in PostgreSQL. Path resolution must reject traversal outside the import storage root.

### Backup/restore requirement for imported originals

The current RoofSpan backup service produces PostgreSQL dumps only. Because imported originals live outside PostgreSQL, this feature must extend backup/restore so those files are not lost.

Each completed backup becomes a **matched backup set** consisting of:

1. the existing PostgreSQL custom-format dump; and
2. a companion import-artifact archive containing `measurement_imports` plus a manifest of relative paths, sizes, and SHA-256 checksums.

Requirements:

- the database dump format remains unchanged for backward compatibility;
- the companion artifact archive uses the same backup timestamp/base name as the dump;
- backup listing/status identifies whether a matching artifact archive exists;
- secondary/off-site copy copies the dump and companion archive as one logical set;
- retention removes matched set members together;
- restore validates the artifact archive/manifest/checksums before database cutover;
- restore stages artifact extraction and uses atomic directory replacement where feasible;
- a legacy backup with no artifact archive remains restorable when its database contains no required import artifacts;
- if a restored database references import artifacts that are absent, restore must surface a clear incomplete-backup error rather than silently succeeding.

This change is limited to preserving measurement-import originals required by this feature. It does not redesign unrelated photo-storage behavior.

### Duplicate handling

SHA-256 is used to detect duplicate source files.

Re-importing the same file must not silently generate duplicate revisions. Office shows that the artifact has already been imported and allows the user to view the previous import.

If the user intentionally reprocesses the same file with a newer parser version, RoofSpan creates a new import proposal. Applying it creates a new measurement revision rather than rewriting the old revision.

### Provenance after application

Add the required `MeasurementRevisionProvenance` record with one row per measurement revision that contains a JSONB provenance map keyed by stable structure/facet/edge/penetration identifiers and field names.

`MeasurementRevisionProvenance`

- `id`
- `revision_id` unique FK
- `provenance` JSONB
- `created_at`
- `updated_at`

For imported/accepted values, provenance records as applicable:

- source import ID;
- source file ID;
- provider;
- provider-native item/reference;
- original parsed value;
- confidence level/reason;
- reconciliation decision;
- accepting user;
- accepted timestamp.

For sketch-derived accepted values, provenance records the sketch document/structure, calculation type, scale source, and acceptance metadata.

## Import confidence model

Use three user-facing levels with deterministic reasons.

### High

Examples:

- recognized structured provider field;
- known units/schema;
- passes internal total checks;
- geometry/topology is valid;
- no conflicting source in the bundle.

### Medium

Examples:

- reliable provider PDF table extraction;
- structured field with incomplete context;
- value passes parsing but has a non-critical total mismatch;
- geometry relationship is likely but not fully proven.

### Low

Examples:

- generic PDF inference;
- ambiguous label association;
- reconstructed diagram geometry;
- conflicting source values;
- unknown schema mapping.

`Accept All High-Confidence` accepts only High items.

Medium and Low items remain unresolved until the user explicitly accepts, edits, or rejects them.

## Reconciliation model

### Never overwrite the existing revision

If a measurement set already contains a revision, importing a report creates a new **proposed revision workflow**.

The import proposal itself remains separate from `MeasurementRevision` during review. The existing revision remains unchanged.

### Reconciliation workspace

The Office screen shows synchronized views for:

**Current Revision | Imported Proposal | Difference | 2D Overlay**

Top-level comparison includes:

- total measured area;
- squares;
- structure count/scope;
- pitch distribution;
- eave LF;
- rake LF;
- ridge LF;
- hip LF;
- valley LF;
- wall/transition LF;
- penetrations;
- sketch/geometry status.

The user can expand:

- Structures;
- Facets;
- Edges;
- Penetrations;
- Existing Roof/Conditions when present.

### Reconciliation actions

Required controls:

- `Accept All High-Confidence`;
- `Accept Section`;
- `Keep Current Section`;
- `Accept Imported` per item;
- `Keep Current` per item;
- `Edit Proposed` per item;
- unresolved-count/status indicator.

The reconciliation UI must never imply that an unresolved value has already become measurement truth.

### Synchronized sketch overlay

The 2D editor provides a comparison overlay between the current revision and imported proposal.

Selecting a reconciliation row selects/highlights the matching structure/facet/edge/penetration in the drawing. Selecting drawing geometry opens the matching reconciliation item.

The UI visually distinguishes:

- unchanged geometry;
- changed geometry;
- imported-new geometry;
- missing/removed geometry;
- unresolved geometry.

### Creating the revision

`Create Measurement Revision` is available only after all required conflicts are resolved.

Applying the import:

1. creates the next draft revision;
2. links it to the prior revision via existing supersedes/revision semantics;
3. creates confirmed child records from accepted/current values;
4. creates the canonical sketch documents;
5. creates the revision provenance record;
6. records audit events and reconciliation decisions;
7. leaves the prior revision untouched.

No takeoff is automatically recalculated.

## Permissions and workflow

### Field/Sales

Authorized Field/Sales users may:

- create/edit draft sketches for measurements they can access;
- calibrate dimensions;
- lock measured edges;
- accept/keep geometry proposals while the revision is editable;
- mark a measurement Field Complete under the existing workflow.

They may not import report files or run Office reconciliation.

### Office/Admin/Owner

Authorized Office/Admin/Owner users may:

- use the full sketch editor;
- import report bundles;
- review parser results/confidence;
- reconcile current vs imported values;
- create the proposed/new measurement revision;
- verify/return/lock under existing measurement rules.

Audit events must identify who accepted imported facts.

## Failure and security handling

### File safety

Before parsing:

- validate file extension and magic/header where feasible;
- impose bounded configurable file-size and bundle-size limits;
- never execute imported content;
- sanitize filenames;
- prevent path traversal when extracting container formats;
- reject/limit malformed or abusive nested archives;
- compute checksum before parser mutation;
- keep parsing failures isolated from the active measurement transaction.

### Parser failure

A malformed/unsupported file never creates a measurement revision.

The import record remains available with:

- status;
- original files;
- parser/provider/version;
- readable error code/message;
- audit timestamp.

### Partial parse

A partial parse may remain in `review_required` with unresolved values. It must not become estimate-driving measurement data until reconciliation is explicitly completed.

### Geometry safety

Block geometry-derived dimensional proposals when:

- scale is unresolved;
- polygon self-intersects;
- facet loop is invalid;
- edge references are broken;
- calculated area is impossible/non-positive;
- connected graph topology is structurally invalid.

Use warnings rather than hard blocks for recoverable anomalies such as:

- small gaps/overlaps;
- suspicious total-area mismatch;
- unusual pitch distribution;
- imported totals that differ from calculated geometry;
- locked measured edge that disagrees with drawn geometry.

## Undo, crash recovery, and persistence

Office and Field maintain an in-session undo/redo stack for sketch operations.

Field additionally persists the latest unsynced sketch document so a crash does not lose onsite measurement work.

Reopening an unsynced structure restores the existing stable local sketch identity and pending mutation; it must not create a duplicate sketch or measurement mutation.

## API boundaries

Required additive API responsibilities are separated as follows; exact route naming may follow existing router conventions.

### Sketch

- list revision sketch documents;
- get one structure sketch document;
- create/update one structure sketch document with optimistic version token;
- validate/derive proposals deterministically from a sketch document.

A concrete route shape may be:

- `GET /api/measurements/{revision_id}/sketches`
- `GET /api/measurements/{revision_id}/sketches/{structure_id}`
- `PUT /api/measurements/{revision_id}/sketches/{structure_id}`

### Import

Required responsibilities:

- create an upload/import bundle;
- add source files;
- detect/parse/normalize;
- retrieve proposal/confidence/status;
- persist reconciliation decisions;
- apply an explicitly resolved import into the next draft revision.

A concrete route shape may be:

- `POST /api/measurement-imports`
- `POST /api/measurement-imports/{id}/files`
- `POST /api/measurement-imports/{id}/parse`
- `GET /api/measurement-imports/{id}`
- `PUT /api/measurement-imports/{id}/reconciliation`
- `POST /api/measurement-imports/{id}/apply`

The separation between sketch persistence, import proposal, reconciliation, and revision application is required even if route names differ.

## UI integration

### Office measurement worksheet

Add two primary actions:

- **Sketch Roof**
- **Import Measurement Report**

If the current revision is immutable, editing starts a new revision under existing rules.

### Office import workspace

Use a staged workflow:

1. Select/drop report files.
2. Detect provider/formats.
3. Parse and show validation/confidence summary.
4. Review comparison and 2D overlay.
5. Resolve Medium/Low/conflicting items.
6. Create Measurement Revision.

### Field measurement screen

Add a sketch entry point tied to the current measurement revision/structure. The user can move between numeric worksheet fields and sketch without creating separate roof records.

## Testing strategy

### Shared geometry engine

Deterministic unit tests must cover:

- distance/scale conversion;
- calibration;
- polygon area;
- pitch-adjusted area;
- connected shared edges;
- facet loop generation;
- split/join edge behavior;
- snapping tolerance;
- self-intersection;
- gap/overlap detection;
- locked-dimension precedence;
- proposal generation;
- manual-polygon validation.

The same fixture must produce the same derived values in Office and Field.

### Field offline tests

Cover:

- create sketch offline;
- edit sketch offline;
- reopen after app restart;
- repeated edits coalesce to one latest mutation;
- Relay unavailable then reconnect;
- stale version conflict;
- no silent last-write-wins;
- photo sync and existing measurement sync regressions remain green.

### Import parser tests

Maintain provider/version golden fixtures for:

- EagleView;
- HOVER;
- GAF QuickMeasure.

Cover:

- recognized provider/format;
- unit normalization;
- facet/pitch mapping;
- edge classification;
- geometry normalization;
- totals cross-check;
- conflicting bundle sources;
- parser-version behavior;
- malformed files;
- unsupported files;
- duplicate checksum;
- generic fallback confidence.

Provider format drift must fail safely into Review Required or Unsupported rather than silently producing different measurement facts.

### Reconciliation tests

Cover:

- Accept All High-Confidence;
- section acceptance;
- per-item accept/keep/edit;
- unresolved conflict blocks apply;
- sketch overlay object mapping;
- imported values create a new draft revision;
- previous revision remains fact-for-fact unchanged;
- provenance is retained;
- no automatic takeoff recalculation.

### Backup/restore tests

Cover:

- DB dump + import-artifact archive created as one logical backup set;
- import artifact manifest/checksums validate;
- secondary/off-site copy contains both set members;
- retention removes paired members together;
- successful restore recovers database metadata and imported originals;
- missing/corrupt companion archive is detected before completing a restore that requires it;
- legacy DB-only backups remain restorable when no imported artifacts are referenced.

### Security tests

Cover:

- invalid MIME/header;
- oversized files/bundles;
- path traversal attempts;
- malformed archives/ESX containers where applicable;
- parser exception isolation;
- no revision creation after parse failure.

## Implementation phases

### Phase 1 — Sketch foundation

Deliver:

- canonical sketch schema;
- shared geometry engine;
- additive persistence/migration;
- Office connected-graph editor;
- Office manual-polygon mode;
- scale/calibration;
- locked measured edges;
- proposal/confirmation flow;
- deterministic geometry tests.

Phase 1 must be independently usable before import support exists.

### Phase 2 — Field sketch

Deliver:

- touch renderer/editor;
- same canonical sketch schema;
- offline cache/mutation behavior;
- crash recovery;
- optimistic version conflict handling;
- parity tests against Office geometry calculations.

### Phase 3 — Import pipeline

Deliver:

- local source-file storage;
- import/import-file/provenance records;
- backup-set extension for import artifacts;
- checksums/security validation;
- provider detection;
- EagleView adapter;
- HOVER adapter;
- GAF QuickMeasure adapter;
- generic fallback parser;
- confidence scoring;
- provider golden fixtures.

### Phase 4 — Reconciliation and apply

Deliver:

- current vs proposal comparison;
- Accept All High-Confidence;
- section/item controls;
- synchronized 2D overlay;
- proposed revision generation;
- provenance/audit persistence;
- no-overwrite/no-auto-recalc guarantees;
- end-to-end regression coverage.

## Non-goals for this implementation

The following are intentionally outside this design:

- a 3D roof editor;
- ordering aerial reports directly from EagleView/HOVER/GAF APIs;
- provider billing/subscription management;
- automatic cloud upload of customer report files;
- AI-generated high-confidence measurements from unknown images;
- automatic estimate/takeoff recalculation after sketch/import changes;
- replacing the existing measurement, estimate, inventory, ABC Supply, Relay, or general backup architectures beyond the required import-artifact backup extension;
- importing reports from RoofSpan Field.

Future work may add direct provider ordering/API retrieval, 3D visualization, satellite imagery workflows, or additional provider adapters without changing the canonical sketch/import contracts defined here.

## Compatibility and migration requirements

- All database changes are additive and use Alembic.
- Existing revisions without sketches continue to work unchanged.
- `MeasurementFacet.geometry` remains optional and backward compatible.
- Existing measurement API consumers retain current semantics unless explicitly requesting sketch/import data.
- Existing Field cache data can migrate without losing current measurement/photo queues.
- Existing accepted quote/job provenance remains bound to the exact original measurement revision.
- Existing DB-only backups remain supported under the compatibility rule above; new imports participate in the matched backup-set extension.
- Existing photo-sync contract must remain green throughout this work.

## Definition of done

This feature is complete only when all of the following are true:

1. Office and Field can create/edit the same 2D roof sketch model.
2. Connected graph is the default and manual polygons are supported.
3. Scale calibration and locked measured edges work without silently rewriting confirmed values.
4. Geometry proposals require explicit acceptance before changing measurement facts.
5. Field sketch work survives offline use, restart, and reconnect.
6. Office can import known EagleView, HOVER, and GAF QuickMeasure report artifacts supported by the adapter fixtures.
7. Office can attempt safe generic fallback parsing for supported unknown files.
8. Original source files/checksums/parser metadata are preserved locally.
9. New backups preserve required import originals as a verified companion artifact set and restore them with the database.
10. Confidence is field/item specific and `Accept All High-Confidence` never accepts Medium/Low values.
11. Existing measurements are never overwritten by an import.
12. Reconciliation supports high-confidence bulk, section, and item-level decisions with a synchronized 2D overlay.
13. Applying an import creates a new draft measurement revision with provenance and leaves prior revisions unchanged.
14. Parser/geometry failures cannot create a measurement revision or corrupt the active one.
15. Takeoff/estimate recalculation remains explicit.
16. Geometry, offline-sync, import, reconciliation, migration, backup/restore, security, photo-sync, and existing measurement regression tests are green.
