# RoofSpan — Deterministic Roof-Framing Solver (Plan for a fresh fork)

> Purpose: replace the current heuristic "fan-out" placement with a real roof-framing solver that turns
> authoritative Measurements into a 2D plan sketch that actually looks like the roof (hip/gable core +
> dormers + real concave valleys). Shared by **Office** and **Field** via `packages/roof-sketch-core`.
> Read this whole file first. Work in stages; each stage is independently testable in Node.

---

## 0. Why we're here (context)
- The Measurements → Proposed Roof Sketch feature deterministically generates a 2D sketch. It works for
  SIMPLE roofs: single plane, simple gable, standard 4-hip. For anything more complex it returns
  "Needs review".
- We added a **resolution-driven placement** step (`resolvePlacement.js`): the engine asks the user
  "which side of F1 does F3 sit on?" and lays the roof out from the answers.
- PROBLEM (confirmed by the user with screenshots): the current approach BFS-attaches every plane as a
  rectangle/triangle to ONE anchor plane and fans them outward. For a real hip-roof-with-dormers this
  produces a pinwheel of overlapping triangles that looks nothing like the roof, and trips the
  "Facet interiors overlap" validator. Valleys were (wrongly) drawn as outward spikes.
- DECISION: build a proper roof-framing solver (this plan). The heuristic in `resolvePlacement.js` is a
  dead-end for complex roofs and should be REPLACED by the new solver (keep its scaffold/UI plumbing).

### The golden target (the user's actual roof — use as the primary fixture)
Structure "House", 2498 SF, 8 planes. Roof planes (label · pitch · area · W×L):
```
F1  8/12  625 SF  25×25      F5  10/12 126 SF  9×14
F2  8/12  625 SF  25×25      F6  10/12 126 SF  9×14
F3  8/12  310 SF  15.5×20    F7   6/12 126 SF  9×14
F4  8/12  310 SF  15.5×20    F8   6/12 250 SF  12.5×20
```
Roof lines (totals): Eave 90.0, Ridge 34.0, Hip 104.0, Valley 80.0, Rake 36.0, Sidewall 32.0 LF.
Penetrations: Pipe Boot ×3, Exhaust Vent ×3, Static Vent ×5, Skylight ×1.
Interpretation: F1/F2 = main hip/gable core (25×25 each, shared ridge), F3/F4 = hip-end planes
(15.5×20), F5–F8 = dormers/secondary sections. The hand-drawn "Should" is a rectangular main roof with
hip ends and two front dormers. Solver output must resemble THAT.

---

## 1. Current code map (what to keep / replace)
Shared engine: `packages/roof-sketch-core/`
- `generateSketchGeometry.js` — orchestrator. `_layoutConnected()` single-component branch currently calls
  `planPlacement`/`layoutFromResolutions`. **Hook the new solver here.** Keep the simple paths
  (`_tryStandardHip`, single-plane, gable) — they work.
- `resolvePlacement.js` — heuristic BFS scaffold + fan-out layout. **KEEP** `planPlacement()` (the
  per-plane side-choice scaffold + `placement_requests` are reused by the UI). **REPLACE** the layout
  (`layoutFromResolutions` rectangle/triangle fan-out) with the new framing solver, OR add a new
  `frameRoof.js` and route to it.
- `schema.js` — `createSketchDocument`/`normalizeSketchDocument`; document has `vertices`, `edges`,
  `facets`, `penetrations`, `scale`, `placement_resolutions` (already added — persists side choices).
- `geometry.js` — `distance`, `polygonArea`, `pitchAdjustedArea`, `planRunFromSlope(width,pitch)`
  (deprojects a sloped width to plan run — CRITICAL), `calibrateScale`, `segmentsCross`,
  `projectPointToSegment`, `edgeGeometryLengthFeet`.
- `topology.js` — `validateSketch(doc)` (canonical validator; output MUST be valid: no overlapping facet
  interiors, closed facets, shared vertices at junctions).
- `edgeDimensions.js` — `edgeDimension(doc,edge)` → per-line LF label (already shows geometry/confirmed/
  drawn). Length labels work; keep.
- `index.js` — public exports. Add new solver exports here.
- `test/` — Node tests (`node <file>`), e.g. `dimensionalSemantics.node.test.js`,
  `resolvePlacement.node.test.js`. Add `frameRoof.node.test.js`.

UI (both consume the shared engine identically):
- Office: `frontend/src/components/roof-sketch/RoofSketchEditor.jsx` (generate/regenerate handlers,
  `resolutions` state, `renderPlacementResolver`), `RoofSketchCanvas.jsx` (SVG render; edge dims;
  `data-testid=edge-dim-<id>`, `placement-resolver`, `placement-side-<plane>`, `placement-apply-btn`).
- Field: `mobile/src/screens/RoofSketch.js` (mirror handlers + touch side-picker
  `field-placement-side-<plane>-<key>`), `mobile/src/components/RoofSketchCanvas.js` (react-native-svg).
- Field feeds the engine via `mobile/src/sketchMeasurementsSummary.js` `scopeStructureForGenerator()`.

### Hard invariants (do NOT break)
- Deterministic. No AI/LLM geometry. Same input ⇒ byte-identical output.
- Never fabricate dimensions silently. If under-constrained, place best-effort and emit an
  `approximations` diagnostic (severity warning/error), never a silent guess.
- Dimensional semantics: `length_ft` = ridge/eave-parallel; `width_ft` = sloped depth ⇒ must be
  deprojected via `planRunFromSlope(width_ft, pitch_rise)` to get plan-view run. (This guard is tested in
  `dimensionalSemantics.node.test.js` — keep it green.)
- SVG canvas y grows DOWN ⇒ "North" = smaller y (top). Keep cardinal/screen mapping consistent.
- Output must pass `validateSketch()` (no overlapping interiors).
- The simple archetypes (single/gable/standard-hip) must keep working (don't regress them).

---

## 2. Target architecture — a framing solver (not a per-plane fan-out)
Model the roof the way it is framed, from the RIDGE network outward. New module `frameRoof.js`.

Core idea: build the roof from its **ridge lines and eave rectangle(s)**, not by hanging planes off a
single anchor. Ridges are the spine; planes are the slopes between a ridge and an eave; hips/valleys are
the intersections between adjacent slope planes.

### Inputs
`{ structure, facets[], edges[], penetrations[], resolutions[] }` (same as today). Each facet:
`{ id, structure_id, label, pitch_rise, width_ft, length_ft, area_sqft, orientation_azimuth? }`.
Each edge: `{ id, edge_type(ridge|hip|valley|dead_valley|eave|rake|sidewall), length_ft, facet_id,
facet_id_secondary? }`. `resolutions[]` = user side/host choices where the topology is ambiguous.

### Output
A valid sketch `document` (vertices/edges/facets/penetrations, scale.resolved=true, feetPerUnit=1) plus
`{ readiness, resolved_planes, unresolved_planes, approximations[], placement_requests[] }`.

---

## 3. Staged build (each stage: implement → Node test → keep green)

### Stage 0 — Foundations & fixtures (start here)
- Create `test/frameRoof.node.test.js` and encode fixtures: (a) simple gable, (b) standard hip,
  (c) the 8-plane golden roof above (F1–F8 + the listed edges — synthesize plausible facet↔edge links),
  (d) a gable + one front dormer. Add helper asserts: `validateSketch` valid, no facet-interior overlap,
  total plan-projected footprint area ≈ measured footprint (within tolerance), plane count matches.
- Build a tiny geometry toolkit if needed on top of `geometry.js` (segment intersection, polygon offset,
  point-in-polygon, ridge/eave classification helpers).

### Stage 1 — Ridge-based core: gable & standard hip (reproduce current good behavior, new engine)
- Group facets into a **ridge component**: facets sharing a ridge are the two slopes of a gable; a plane
  with hips on both ends + a ridge is a hip main plane.
- Lay out the eave rectangle from eaves; place the ridge parallel to eaves at plan-run depth
  (`planRunFromSlope(width,pitch)`); build gable (2 rects) or hip (2 trapezoids + 2 end triangles).
- Acceptance: gable & standard-hip fixtures render identical-in-spirit to the existing engine and pass
  validation. This proves the ridge-first method before adding complexity.

### Stage 2 — Multi-ridge / cross-gable cores
- Support multiple ridges (e.g., an L or T or cross): each ridge yields a core block; blocks connect
  where their eaves/ridges meet. Use `resolutions` (which side / which ridge is primary) only where the
  measurements genuinely allow >1 arrangement. Anchor the longest ridge; orient others relative to it.
- Acceptance: an L-shaped 4-plane roof and a cross-gable render correctly; valleys appear where two core
  blocks meet (Stage 4 refines the valley geometry).

### Stage 3 — Hip ends & rake ends on cores
- For a core block, classify each end as gable (rake, vertical triangle → flat rake edge) or hip
  (hip end → triangular plane whose apex sits on the ridge line at the correct inset). Use the measured
  hip length + pitch to place the hip apex. F3/F4 in the golden roof are hip ends of the F1/F2 core.
- Acceptance: golden roof's F1–F4 render as a proper 25×25 hip main roof with 15.5×20 hip ends; no
  overlaps; hip LF ≈ measured.

### Stage 4 — Real concave valleys
- A valley is the concave intersection of two slope planes from DIFFERENT cores/wings. Compute the valley
  line as the plan-view intersection of the two planes (from ridge-meets-ridge point down to the
  eave/eave corner). Valleys are INWARD/concave — NOT outward spikes. Trim both planes to the shared
  valley line (miter). This is the crux of "valley-miter reconciliation" done correctly.
- Acceptance: cross-gable and dormer fixtures show valleys as concave shared edges; both planes share the
  exact valley vertices; total area conserved; validator passes.

### Stage 5 — Dormers seated on host planes
- A dormer (e.g., F5–F8) sits ON a host main plane. Seat its footprint on the host, its lower edge a
  valley/sidewall against the host, ridge parallel to host ridge (or perpendicular for a gable dormer).
  Use `resolutions` to pick the host plane + position band when ambiguous. Flag approximation for exact
  along-host position (measurements rarely fix it).
- Acceptance: gable+dormer fixture and the golden roof's F5–F8 render as dormers on the main planes, not
  free-floating spikes.

### Stage 6 — Penetrations, approximations, readiness, validation
- Place penetrations with known positions; mark position-unknown ones as manual-placement (existing
  pattern). Aggregate `approximations[]`. Set readiness: high_confidence (fully constrained + valid),
  needs_review (ambiguous, emit `placement_requests`), partial (some planes placed, rest listed).
- Always run `validateSketch`; never emit overlapping interiors — if a layout would overlap, downgrade to
  partial/needs_review rather than shipping garbage.

### Stage 7 — Wire into orchestrator + UI + persistence
- Route `generateSketchGeometry._layoutConnected()` complex branch to `frameRoof`. Keep
  `planPlacement()` scaffold so the UI still asks side/host questions ONLY where the solver reports
  genuine ambiguity (`placement_requests`). Persist choices in `document.placement_resolutions`
  (already supported) so Office↔Field parity + offline safety hold.
- UI already renders the resolver (Office `renderPlacementResolver`, Field touch picker) and per-line LF
  labels — reuse as-is. Verify both apps after wiring.

---

## 4. Test & verification strategy
- Node golden tests are the backbone (deterministic, no UI needed): `node packages/roof-sketch-core/test/frameRoof.node.test.js`.
  Assert per stage. Keep `resolvePlacement.node.test.js` and `dimensionalSemantics.node.test.js` green.
- Regression: `cd mobile && yarn test:sketch` (core regression), plus `test:measurements`.
- Office E2E: use `testing_agent` (frontend) after wiring — verify the golden roof renders like the
  "Should" drawing, validation shows "No issues", LF labels correct, adopt+Save (PUT 200), and simple
  roofs still auto-draw with no resolver. Field can't run natively in this env → rely on shared-core tests.
- After each stage/commit, direct the user to "Save to Github" (agent cannot push; local commits only).

## 5. Definition of done (feature-level)
- The golden 8-plane roof auto-generates (after any genuinely-needed side/host choices) into a sketch that
  visually matches the hand-drawn "Should": rectangular main roof, hip ends, two dormers, concave valleys.
- `validateSketch` valid (no overlaps). Areas/LF within tolerance of measurements. Deterministic.
- Works identically in Office and Field (shared engine). Simple roofs unregressed. Approximations flagged.

## 6. Pitfalls observed (avoid repeating)
- DON'T attach every plane to one anchor and fan outward → pinwheel/overlap. Build from ridges/eaves.
- DON'T draw valleys as outward triangles → spikes. Valleys are concave plane intersections.
- DON'T let a plane's along-length be forced to the parent side length; use its own measured dims.
- DON'T silently pick an arrangement when measurements allow several — emit a placement_request.

## 7. Environment / logistics
- Monorepo: root npm workspace lockfile `package-lock.json`. Frontend uses a symlinked
  `frontend/node_modules/@roofspan/roof-sketch-core` → `/app/packages/roof-sketch-core` (edits reflect).
  If Office dev build doesn't pick up core changes, re-check the symlink.
- Stack locked: Expo 54.0.37 / RN 0.81.5 / React 19.1 / React Navigation 7.x. Do not upgrade.
- Preview URL from `frontend/.env` REACT_APP_BACKEND_URL (currently sketch-geometry-1...); backend on
  `/api`; services via supervisor (`sudo service supervisor start` if down; backend+frontend+postgres+
  mongo). Owner login + more in `/app/memory/test_credentials.md`
  (pjacobsen@asgardsolution.io / RoofSpan#Owner2026). A seeded complex sketch exists on lead
  e7b41ad7-cc50-4a56-ae70-30558c974c4a.
- Git: agent commits locally only; user pushes via "Save to Github". Use targeted commits per stage.
- Do NOT start Plan 2 (aerial/report imports). This solver is the current focus.

## 8. Suggested first actions on fork
1. Read this file, `PRD.md`, and skim `generateSketchGeometry.js`, `resolvePlacement.js`, `geometry.js`,
   `topology.js`, `schema.js`.
2. Create `test/frameRoof.node.test.js` with the fixtures (Stage 0). Encode the golden roof.
3. Implement Stage 1 (ridge-based gable/hip), get its tests green, commit. Proceed stage by stage.
4. Only wire the UI (Stage 7) once the engine produces valid, faithful geometry for the golden roof.
