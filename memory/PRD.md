# RoofSpan — Product Requirements & Status

## Outcomes caching + conflict diff preview (Field) (2026-06) — DONE (deterministic contracts); no git ops
Two Field UX enhancements (mobile-only; no backend change):
- **Outcomes caching:** NEW `cache.visitOutcomes()` read-through (`visit_outcomes` cache key) — `Property.js` renders the six visit labels instantly and keeps them correct on a cold/offline open (falls back to the durable cached list; refreshes from `GET /api/visit-outcomes` when online). Removed the ad-hoc `api.get` in the screen.
- **Conflict diff preview:** NEW pure `fieldReconcile.conflictDiff(mutation)` returns the edited fields that ACTUALLY differ between the rep's local mutation body and the authoritative server snapshot (do_not_knock, DNK reason, notes, visit outcome). The `Property.js` conflict banner now shows "Office: X · You: Y" rows so the rep chooses Use-Office / Keep-mine with full context.
- **Verification:** `field_reconcile.node.test.js` 12→**13** (conflict diff: only edited+differing fields; identical values yield no row; unedited fields hidden). Full `test:sketch` (sketch16/ack26/live-status16 + others) PASS; babel-preset-expo parse OK for Property/fieldReconcile/cache. Files: MODIFIED `mobile/src/cache.js`, `mobile/src/fieldReconcile.js`, `mobile/src/screens/Property.js`, `mobile/src/tests/field_reconcile.node.test.js`. No backend/dependency/lockfile change.
- **Limitation:** RN screen code-reviewed + Babel-parsed, NOT device-tested (Expo can't run on a device in-pod); the read-through cache and diff logic are under contract.


## Optimistic-concurrency tokens (real 409s) + Office consumes shared outcomes endpoint (2026-06) — DONE (backend pytest); no git ops
- **Server conflict tokens (real 409 → conflict banner end-to-end):** Property mutations now use `updated_at` as an optimistic-concurrency token (no schema migration). `VisitIn`/`PropertyPatch` (Office) and `MobileVisitIn`/`MobilePropertyPatch` (Field) accept optional `expected_updated_at`; shared `services.property_detail.conflict_if_stale(db, p, expected_updated_at)` raises **409** with `detail = {code:"conflict", server:<canonical PropertyDetail>}` when the token no longer matches. Wired into Office `patch_property`/`create_visit` and mobile `patch_property`/`create_visit`. Field `Property.js` sends `expected_updated_at: prop.updated_at` on DNK/visit; the queue already captures `serverValue = detail.server` on 409 → `conflictMutationForProperty` → the Use-Office/Keep-Local banner (from the previous iteration) now fires from a REAL server conflict. Token omitted → backward-compatible success.
- **Office consumes the shared outcomes endpoint:** `frontend/src/components/PropertySheet.jsx` fetches `GET /api/visit-outcomes` on open (fallback to a local list) and renders both the visit-outcome `Select` and history labels from it — Office and Field now both read the six labels from the one backend source (`visit_outcomes.py`).
- **Verification:** NEW hermetic `backend/tests/test_property_concurrency.py` **1 passed** (no-token succeeds + advances updated_at; matching-token succeeds; stale-token PATCH → 409 with authoritative `detail.server`; stale-token visit → 409; fresh-token visit created). Regressions: `test_property_parity` 1, `test_mobile_property_patch` 1, `test_field_property_live` 17, `test_mobile_api` 11, `test_mobile_salesperson_p1` 23 — all PASS. Mobile `field_reconcile.node.test.js` 12 PASS; babel-preset-expo parse OK (Property/fieldReconcile/sync). Office frontend recompiled cleanly (pre-existing warnings only). Files: MODIFIED `backend/schemas_phase2.py`, `backend/services/property_detail.py`, `backend/routers/properties.py`, `backend/routers/mobile.py`, `frontend/src/components/PropertySheet.jsx`, `mobile/src/screens/Property.js`; NEW `backend/tests/test_property_concurrency.py`. No migration, dependency, or lockfile change.
- **Limitation:** Field RN screen (token send + banner) code-reviewed + Babel-parsed, NOT device-tested (Expo can't run on a device in-pod); the 409 path, conflict-plan resolution, and Office fetch are all covered by pytest/contracts (Office verified by clean compile).


## Aliases retired + shared visit-outcomes endpoint + Property conflict resolution (2026-06) — DONE (backend pytest + deterministic contracts); no git ops
Three follow-ups delivered together (backend + Field mobile):
- **Retired temporary compat aliases:** removed `owner_name`/`owner_phone`/`existing_lead_id` from the mobile Property response — `MobilePropertyDetail` and `services.property_detail.with_field_compat_aliases` deleted; both `GET`/`PATCH /api/mobile/properties/{id}` now return the canonical `PropertyDetail` (identical to Office). Field `Property.js` reads canonical `contacts[]` (owner/renter) + `lead_id` only; `fieldReconcile` lead_create writes only `lead_id`. Backend tests updated to assert the aliases are GONE.
- **Shared visit-outcomes endpoint:** NEW `GET /api/visit-outcomes` (`routers/meta.py`, any authenticated user) returns the canonical six `{value,label}` from `visit_outcomes.py`. Field fetches it on focus (falls back to a local list offline) so Office and Field render from ONE backend source.
- **B3C-style Property conflict resolution:** `fieldReconcile.resolveConflictPlan(mutation, choice)` + `sync.conflictMutationForProperty(propertyId)` / `sync.resolveFieldConflict(client_id, choice)`. When a Property/Visit/DNK mutation is in `conflict` state, `Property.js` shows a "Sync conflict — review required" banner with **Use Office version** (drops the local mutation, adopts the server snapshot into detail + canvass caches) and **Keep my change** (re-queues the rep's exact body, re-attempts). Never deletes work without the rep's explicit choice. (Note: the backend does not currently emit 409 for Property/DNK/visit — this is the defensive client resolution path; sketches remain the live 409 source.)
- **Verification:** backend `GET /api/visit-outcomes` E2E returns the six; pytest `test_property_parity` 1 + `test_mobile_property_patch` 1 + `test_field_property_live` 17 (now assert aliases removed + parity) = 19 PASS; regressions `test_mobile_api` 11, `test_mobile_salesperson_p1` 23. Mobile `field_reconcile.node.test.js` 11→**12** (adds conflict use_server/keep_local/noop; lead_create no-alias); full `test:sketch` (sketch16/ack26/live-status16 + others) PASS; babel-preset-expo parse OK for Property/fieldReconcile/sync/cache. Files: NEW `backend/routers/meta.py`; MODIFIED `backend/routers/mobile.py`, `schemas_phase2.py`, `services/property_detail.py`, `server.py`, `tests/test_property_parity.py`, `tests/test_field_property_live.py`, `mobile/src/{fieldReconcile,sync,cache,screens/Property}.js`, `mobile/src/tests/field_reconcile.node.test.js`. No dependency/lockfile change.
- **Limitation:** RN Field screen (outcomes fetch + conflict banner) was code-reviewed + Babel-parsed but NOT device-tested (Expo cannot run on a device in this pod); reducers/endpoint/gating are under contract.


## Property & Map Cache Synchronization — Field reconciliation after acknowledgement (2026-06) — DONE (deterministic contracts); no git ops
Root synchronization issue: a successful Field mutation left PostgreSQL, the Property-detail cache and the Map/canvass Property cache showing DIFFERENT states — optimistic local values were never reconciled to the authoritative server state, and canvass caches weren't touched at all (Map needed an app restart to converge).
- **Pure reducers (`mobile/src/fieldReconcile.js`, new, CommonJS/testable):** `reconcilePropertyDetail(kind, serverValue, cur)` (property_patch → full canonical replace; visit → replace optimistic `pending-*` placeholder with authoritative visit + set last_outcome/last_visited_at + do_not_knock when applicable; lead_create → set lead_id/existing_lead_id); `reconcileCanvassFeatures(kind, serverValue, propertyId, cur)` (patch ONLY the matching GeoJSON feature: do_not_knock, owner_occupied, last_outcome, last_visited_at, has_lead); `optimisticCanvassPatch`; `propertyIdForMutation` (serverValue → path → body).
- **Acknowledgement reconciliation (`sync.js::_reconcileFieldAcks`, called after `_reconcileSketchAcks` in runSync):** for each SYNCED visit/property_patch/lead_create row only, applies authoritative server state into `property:{id}` and every cached `section:*:props` list (via new `storage.listCacheNames(prefix)` + `mutateCache`). Pending/failed/conflict + other kinds are skipped (no data loss). Generation-guarded writeback (`saveMutationIfCurrent`) + queue/idempotency/retry/conflict/scope isolation all preserved and untouched.
- **Optimistic updates (`Property.js` + `cache.patchCanvassFeature`):** visit and DNK on/off immediately patch the local Property detail AND all canvass feature caches so the screen and Map reflect the pending change before Office acknowledges; the authoritative reducer overwrites on ack.
- **Property detail refresh:** on focus, `Property.js` uses the existing read-through `cache.property(id)` — fetches canonical detail + refreshes the saved cache when Office is reachable, falls back to the saved copy + `stale` indicator when offline (no refresh loop; load only on focus).
- **Lead reconciliation:** an acknowledged offline lead sets Property `lead_id` (screen flips Create → Open lead on next focus) and canvass `has_lead=true`. Backend idempotency/duplicate prevention unchanged (no backend change this iteration).
- **Verification (deterministic Node contracts):** NEW `field_reconcile.node.test.js` **11** (optimistic visit; authoritative visit ack; optimistic+authoritative DNK ON; optimistic+authoritative DNK OFF; property cache replace; canvass patch isolation; stale/offline no-op; unrelated pending intact; reconnect convergence; lead lead_id+has_lead; propertyIdForMutation). Regressions green: mobile `test:sketch` (sketch16/ack26/live-status16 + others) + `test:reconcile` 11 + measurement_cache/transport/photo 6/2/2; babel-preset-expo parse OK for fieldReconcile/sync/storage/cache/Property. Backend unchanged, re-ran to confirm: mobile_api 11, mobile_salesperson_p1 23, canvass_sections 9, relay 15, property_parity 1, mobile_property_patch 1 — all PASS. Files: NEW `mobile/src/fieldReconcile.js`, `mobile/src/tests/field_reconcile.node.test.js`; MODIFIED `mobile/src/sync.js`, `storage.js`, `cache.js`, `screens/Property.js`, `package.json` (test script only), `.github/workflows/roof-takeoff-contract.yml`. No `mobile/yarn.lock` (stray auto-gen removed); no dependency added.
- **Limitation:** mobile pure-Node/RN logic — the RN screen wiring was code-reviewed + Babel-parsed but NOT device-tested (Expo cannot run on a device in this pod); reducers + storage enumeration + gating are fully under contract.


## Field Property Screen Parity — canonical info + full visit workflow + DNK on/off (2026-06) — DONE (testing_agent verified); no git ops
Field Property screen now exposes the same core home info and canvassing actions as Office, powered by the canonical backend contract from the previous iteration.
- **Canonical Field display (`mobile/src/screens/Property.js` rewritten):** address; property details (type, bedrooms, bathrooms, square_footage, year_built, coordinates); Owner/Renter from `contacts[]` (name, contact_type, occupancy owned/rented/unknown, mailing address, phone, email); Do Not Knock status + reason; visit history with friendly outcome labels; property photos (existing PhotoSection); lead relationship — Open existing lead when `lead_id`, else Create lead. Inspection workflow preserved. Reads canonical fields with temporary alias fallback.
- **Full canonical visit workflow:** all six outcomes (No answer / Not interested / Interested / Callback requested / Appointment set / Do Not Knock) + optional Notes + explicit Save; queues `POST /mobile/visits` with notes. Replaced the old independent 4-item list.
- **DNK on/off:** NEW authorized `PATCH /api/mobile/properties/{id}` (`MobilePropertyDetail` response) — sets do_not_knock/reason/notes; `assert_property_access` enforces property-level authz (sales scope; management broad). Same column-set behavior as Office (no divergent DNK rule). Field toggles ON/OFF via `queueMutation(kind:"property_patch", method:"patch")`.
- **Offline:** uses the existing durable mutation queue; visit (with notes) and DNK changes are queued and reflected LOCALLY immediately via optimistic `setProp` + `patchCachedDetail` (no sync-engine redesign this iteration).
- **Wire parity fix (from testing_agent iteration_53):** mobile detail now returns `MobilePropertyDetail(PropertyDetail + owner_name/owner_phone/existing_lead_id)` so Office and Field emit BYTE-IDENTICAL JSON timestamps (was Pydantic `Z` vs raw `+00:00`).
- **Verification (testing_agent iteration_54: 17/17 live + 2/2 hermetic PASS, no issues, retest_needed=false):** DNK off→on / on→off + notes for authorized caller; unauthorized sales 403 on GET+PATCH; all 6 outcomes accepted + invalid 422 on mobile AND office visit endpoints; canonical parity incl. byte-identical timestamps; lead_id null when only archived leads. Regressions (serial `-n0`): mobile_api 11, mobile_salesperson_p1 23, canvass_sections 9, property_occupancy 3, property_dedup 6 — all PASS. Babel parse of Property.js OK. Files: MODIFIED `mobile/src/screens/Property.js`, `backend/routers/mobile.py`, `backend/schemas_phase2.py`; NEW `backend/tests/test_mobile_property_patch.py` (+ testing_agent's `test_field_property_live.py`).
- **Limitation:** React Native Field UI was code-reviewed + Babel-parsed but NOT device-tested (Expo cannot run on a device in this pod); Field still carries temporary compat aliases and a local outcome list; deeper offline cache convergence deferred to next iteration.


## Unify Office & Field Property/Home Data — canonical Property detail + visit outcomes + Sales IDOR hardening (2026-06) — DONE LOCALLY; no git ops
Backend-only iteration (no Field UI / offline redesign). Root cause: Office `GET /api/properties/{id}` and Field `GET /api/mobile/properties/{id}` independently hand-built DIFFERENT Property representations (Office = full `PropertyDetail` with contacts[]/`lead_id`; Field = flattened dict with `owner_name`/`owner_phone`/`existing_lead_id` and many omitted fields); visit outcomes were hard-coded twice (Office 6, Field 4 — missing callback/appointment) with NO backend validation; and Office `/api/properties/{id}` GET/PATCH/visits/convert-to-lead accepted the Sales role WITHOUT property-level authz (salesperson IDOR by UUID).
- **Canonical Property detail:** NEW `services/property_detail.py::build_property_detail(db, p)` is the single source of truth (all attributes + contacts[] + visits[] + `lead_id` + location_diagnostics + created_at/updated_at). BOTH `routers/properties.py::get_property` (→ `PropertyDetail`) and `routers/mobile.py::get_property` now build from it. `lead_id` = most-recent NON-archived lead (archived-only → null). Added `updated_at` to `PropertyDetail` schema.
- **Field compat aliases (temporary):** mobile response adds `owner_name`/`owner_phone`/`existing_lead_id` via `with_field_compat_aliases()`, derived DIRECTLY from the canonical detail (no separate queries). Marked temporary; removed once Field UI migrates to contacts[]/lead_id.
- **Canonical visit outcomes:** NEW `visit_outcomes.py` (`no_answer/not_interested/interested/callback/appointment/do_not_knock` + labels + `validate_outcome`). Validated via Pydantic `field_validator` on both `VisitIn` (Office) and `MobileVisitIn` (Field) → unsupported values rejected 422. Office frontend already lists the 6; Field UI list migration deferred to next iteration.
- **Authorization hardening:** Office `get_property`/`patch_property`/`create_visit`/`convert_to_lead` now call `mobile_authz.assert_property_access` (Sales limited to canvass/lead/job scope; management broad). Closes the Sales direct-UUID IDOR without exposing an unrestricted endpoint to Field.
- **Verification:** NEW hermetic `tests/test_property_parity.py` (1 scenario, ~30 asserts): endpoint parity on a richly-seeded property, all attributes, non-archived `lead_id` selection (+ archived-newer must not win, archived-only→null), compat aliases match canonical, all 6 outcomes valid + invalid rejected on both schemas, authorized rep OK + unauthorized 403 on BOTH mobile and Office routes. Regressions: `test_mobile_salesperson_p1` 23, `test_mobile_api` 11, `test_canvass_sections` 9, `test_measurement_sketch_survival`+`clone`+`test_property_occupancy`+`dedup`+`parity` 12 — ALL PASS (`-n0`). E2E curl: invalid outcome→422, callback/appointment→201, Office detail returns full canonical keys incl. `updated_at`/`lead_id`. Files: NEW `backend/visit_outcomes.py`, `backend/services/property_detail.py`, `backend/tests/test_property_parity.py`; MODIFIED `backend/schemas_phase2.py`, `backend/routers/properties.py`, `backend/routers/mobile.py`. Field UI + offline/cache sync migration NOT started (next iteration).


## Task 6 Phase B3B2 CORRECTION — monotonic CAS metadata + latest-wins status refresh (2026-06) — DONE LOCALLY; no git ops
Closed the out-of-order async refresh race where overlapping `onSyncChange()` refreshes could finish in the wrong order — either a stale refresh replacing newer CAS base metadata, or the screen flickering `Synced to Office` → `Waiting to sync`.
- **Version-guarded `adoptServerVersion` (controller):** now rejects a stale metadata pair entirely — incoming version < current → ignore version AND base; incoming > current → adopt version + matching base; incoming == current → only FILL a missing base (never replace a known one). Still never touches working geometry, edit generation, history or selection.
- **Latest-wins refresh (wiring + screen):** new `WIRE.nextRefreshSeq(state)` + `WIRE.applySketchRefresh({seq, state, editor, mutation, draft, running, setStatus})`. Each `refreshSync()` claims a monotonically increasing sequence before its async durable reads; on completion it applies CAS metadata, acknowledged generation and screen status ONLY if it is still the newest (`seq === state.seq`), otherwise the whole stale result is discarded. Acknowledged generation is also kept via `Math.max`. Screen refactored to a single `syncStateRef = {seq, acked, localSave}`; no polling/timer added.
- **Critical example proven:** B pending → old refresh reads pending → B succeeds → new refresh reads synced → new completes first (`Synced to Office`, editor v7) → old completes after and is DISCARDED → final state stays `Synced to Office` / v7 (never reverts, CAS/acked not regressed).
- **Verification:** `roof_sketch_live_status.node.test.js` 13→**16** (adds: v7/S7 then stale v5/S5 stays v7/S7 + equal-version base fill/no-replace + working state untouched; latest-wins discards a late stale pending refresh for status/CAS/acked). Full mobile `test:sketch` (…/live-status16) + `test:measurements` + `test:transport` + photo 6/2/2 PASS; babel-preset-expo parse OK for controller/wiring/screen. Files: MODIFIED `mobile/src/roofSketchFieldController.js`, `roofSketchFieldWiring.js`, `screens/RoofSketch.js`, `tests/roof_sketch_live_status.node.test.js`. Mobile-only; no backend/web surface; no dependency; no `mobile/yarn.lock`. B3C/B3D/Phase C/status-chip cosmetics NOT started; no backend CAS change.


## Task 6 Phase B3B2 — truthful live Field sketch sync status + open-editor CAS adoption (2026-06) — DONE LOCALLY; no git ops
Made the open Field Roof Sketch screen reflect its authoritative, STRUCTURE-SPECIFIC sync state while the rep works, and let the open editor adopt newly acknowledged CAS metadata without disturbing the rep's work. Uses only the existing `onSyncChange()` events (no polling/timer, no new sync engine).
- **Structure-specific status (never global queue):** new `sync.currentSketchMutation(rev, struct)` reads ONLY the deterministic `measurement-sketch-update:<rev>:<struct>` row; `sync.isSyncing()` exposes the active-run flag. Pure `WIRE.fieldSketchSyncStatus({localSave, mutation, running, currentGeneration, acknowledgedGeneration})` returns exactly one of: `Saving on device…` / `Saved on device` / `Waiting to sync` / `Synchronizing…` / `Synced to Office` / `Conflict — review required` / `Sync issue — retry needed`. Device-durability wins first; then this structure's mutation: conflict→review, durable failed→`Sync issue — retry needed` (NOT "Waiting to sync"), pending→`Synchronizing…` if running else `Waiting to sync`; `Synced to Office` ONLY when the CURRENT committed generation is the acknowledged one (an older-gen ack with newer local work is never Synced). A photo/another structure can't change this sketch's status.
- **Open-editor CAS adoption:** new controller `adoptServerVersion({documentVersion, baseServerDocument})` — monotonic version raise + base update, NEVER touches working geometry, `editGeneration`, undo/redo history or selection (`documentVersion`/`baseServerDocument` made mutable; getters added).
- **Screen wiring (`RoofSketch.js`):** subscribes to `onSyncChange` (start/end toggles `running`), on each event re-reads this structure's mutation + durable draft, calls `adoptServerVersion` (from the B3B1-advanced durable draft, else the synced `serverValue`), tracks acknowledged generation, and sets the combined status. Initial label is source-aware: fresh Office load→`Synced to Office`, cache→`Offline/cached sketch`, brand-new→`New sketch`; an untouched cached/new sketch is NOT relabelled by an unrelated sync event. Retry button now also covers `Sync issue — retry needed` (re-persist + `syncNow`).
- **Critical example proven (controller+status):** server v5 → Edit A → newer Edit B → A-ack v6 (B preserved, editor adopts v6, B's document/generation unchanged, status `Waiting to sync`/`Synchronizing…`, NOT Synced) → B-ack v7 (row synced at B's generation → `Synced to Office`, editor now uses v7).
- **Verification:** NEW `roof_sketch_live_status.node.test.js` **13** (all 6→7 status rules incl. new failure state, device precedence, structure isolation via the real id fn, adopt without touching working state + monotonic, full A→B→A-ack→B-ack). Full mobile `test:sketch` (…/ack26/**live-status13**) + `test:measurements` + `test:transport` + photo 6/2/2 PASS; babel-preset-expo parse OK for controller/wiring/sync/screen. Files: MODIFIED `mobile/src/roofSketchFieldController.js`, `roofSketchFieldWiring.js`, `sync.js`, `screens/RoofSketch.js`, `package.json` (test script only — no dependency), `.github/workflows/roof-takeoff-contract.yml`; NEW `mobile/src/tests/roof_sketch_live_status.node.test.js`. No `mobile/yarn.lock` (stray auto-gen removed). Mobile-only; no backend/web surface. B3C (conflict-resolution UI: Use Server/Keep Local, Base/Local/Office panel), B3D (live locking, AppState/background), Phase C NOT started.


## Task 6 Phase B3B1 DATA CONSISTENCY — CAS version and base document stay together (2026-06) — DONE LOCALLY; no git ops
Fixed a reverse-order consistency gap: a late local draft was correctly floored v5→v6 but its `base_server_document` could remain the stale v5 document, showing the wrong Base in future conflict review.
- **Shared `reconcileDraftWrite` now aligns the base:** gained an optional 4th arg `knownServer` = the authoritative cached server sketch `{document_version, document}`. When the cached server (or an existing durable draft) raises the CAS version above incoming's own base, the matching authoritative server DOCUMENT becomes `base_server_document` (picked as the base of the highest-version candidate among incoming/existing/cachedServer). Never fabricates a base (only adopts a real document); never regresses a newer existing/incoming base; generation protection unchanged. The local sketch document is NOT replaced.
- **Wired:** `storage.saveSketchDraftIfCurrent` passes the already-read cached `server` value into `reconcileDraftWrite`. Opposite ordering (B first, then ack A) already advanced the base via `applySketchAck`'s superseded path (unchanged).
- **Required example proven:** ack v6 (cached S6) → late B(v5/base S5) ⇒ durable B = {local doc B, edit_generation B, document_version 6, base_server_document S6}. Restart restores BOTH v6 and S6.
- **Verification:** `roof_sketch_ack.node.test.js` 20→**26** (adds: forward ordering B(v6/S6) with local doc+gen unchanged; restart restores v6+S6; opposite ordering B(v6/S6); existing newer base S7 not regressed by older cached S6; no base fabricated when none available; generation protection intact). Full mobile `test:sketch` (…/ack**26**) + `test:measurements` + `test:transport` + photo 6/2/2 PASS; babel-preset-expo parse OK. Files: MODIFIED `mobile/src/roofSketchAck.js` (`reconcileDraftWrite` base alignment), `mobile/src/storage.js` (pass `server`), `tests/roof_sketch_ack.node.test.js`. Mobile-only; no backend/web surface; no new dependency. B3B2/B3C/B3D/Phase C NOT started.


## Task 6 Phase B3B1 FINAL CORRECTION — late draft write can never regress CAS (2026-06) — DONE LOCALLY; no git ops
Closed the last reverse-order race: an Office ack establishes v6, then a later local draft write created with a stale base (v5) could still regress the durable draft because `saveSketchDraftStrict` did a blind serialized write.
- **CAS-monotonic strict draft write:** new `storage.saveSketchDraftIfCurrent(draftKey, detailKey, incoming)` runs the read-modify-write in ONE `_serialize` critical section: reads the current draft AND the cached authoritative server sketch, computes `knownServerVersion = max(existing draft base, cached server version)`, then applies the shared `reconcileDraftWrite(existing, incoming, knownServerVersion)` rule — rejects an older `edit_generation` (no-op, not an error), allows a newer generation but floors its `document_version` to the highest known server version. `cache.saveSketchDraftStrict` now routes through it (storage errors still PROPAGATE for the durability contract; keys passed in so storage stays generic).
- **Required example proven:** A(v5) → Office accepts A=v6 → ack completes (A draft retired) → late B write carrying v5 ⇒ durable B = {edit_generation:B, document:B, document_version:6} (never 5). Restart: editor resolves from the durable B draft, CAS version = 6, next staged mutation uses `expected_version:6`. Opposite ordering (B first, ack A second) keeps B and advances 5→6 (via existing `applySketchAck` superseded path).
- **Verification:** `roof_sketch_ack.node.test.js` 16→**20** (adds: late-B-after-ack floored to v6; restart retains v6 + staging uses 6; opposite ordering keeps B at v6; late older generation cannot overwrite/regress). Full mobile `test:sketch` (…/ack**20**) + `test:measurements` + `test:transport` + photo 6/2/2 PASS; babel-preset-expo parse OK. Files: MODIFIED `mobile/src/storage.js` (`saveSketchDraftIfCurrent` + `reconcileDraftWrite` import), `mobile/src/cache.js` (`saveSketchDraftStrict` rewire), `tests/roof_sketch_ack.node.test.js`. Mobile-only; no backend/web surface; no new dependency. B3B2/B3C/B3D/Phase C NOT started.


## Task 6 Phase B3B1 CORRECTION — atomic acknowledgement reconciliation (2026-06) — DONE LOCALLY; no git ops
Made the successful-acknowledgement reconciliation ATOMIC against a concurrent newer local edit (C), fixing three defects in the base B3B1 `_reconcileSketchAcks`.
- **Same serialized draft boundary (user adj. 1):** new `storage.putCacheSerialized` + `storage.mutateCache` run inside the existing `_serialize` critical section; `cache.saveSketchDraftStrict`/`clearSketchDraft` now use `putCacheSerialized`, so the editor's draft write (generation C) and the ack read/retire are MUTUALLY serialized on the same scoped draft key. `mutateCache(draftKey, fn)` decides retire/preserve against the FRESHLY re-read draft → C is never deleted/clobbered, only the exact acked generation retires.
- **Durable, gen-safe expected_version floor (user adj. 2):** new `storage.floorPendingSketchExpectedVersion(clientId, serverVersion)` operates on the LIVE stored row inside `_serialize` (pure planner `roofSketchAck.planExpectedVersionFloor`): raises `body.expected_version = max(current, server)` while preserving the row's `document`, `local_edit_generation` and `mutation_generation`; never resurrects a missing row; scoped to the account. Replaces the stale load→`saveMutation` rebase (closes B→C supersession with no read/write retry loop).
- **Raw cache shape:** the acknowledged sketch is now cached RAW (`putCache(detailKey, serverValue)`) — no `{data,stale,cachedAt}` read-through envelope (was double-wrapping the slot).
- **Shared CAS floor wired cross-module:** `roofSketchSyncCoordinator` now reads/writes the module-scope `roofSketchCasFloor`; a late ack in `sync.js` calls `noteVersion`, so a freshly opened coordinator (empty own floor) is still floored (in-memory live-staging convenience; DURABLE storage floor above remains authoritative across restart).
- **Verification:** `roof_sketch_ack.node.test.js` 10→**16** (adds: newer C preserved+advanced not deleted; matched retires; cleared slot not resurrected; durable floor preserves document+both generations; monotonic/missing/synced/already-floored no-op; cross-module reverse-race floors a fresh coordinator). Full mobile `test:sketch` (core26/topo31/edge10/cache15/queue-race25+11+8/view13/editor44/live-wiring36/sync16/**ack16**) + `test:measurements` + `test:transport` PASS; babel-preset-expo parse OK for storage/sync/cache/coordinator/ack/casFloor. Files: MODIFIED `mobile/src/{storage,sync,cache,roofSketchAck,roofSketchSyncCoordinator}.js`, `tests/roof_sketch_ack.node.test.js`; NEW (already present) `mobile/src/roofSketchCasFloor.js`. No new dependency. Change is mobile-only (no backend/web-frontend surface). B3B2/B3C/B3D/Phase C NOT started.


## Task 6 Phase B3B1 — safe server acknowledgement + CAS rebase (2026-06) — DONE LOCALLY; no git ops
Generation-safe processing of successful sketch acknowledgements — advances the authoritative CAS version without ever deleting/overwriting newer local work or regressing the version.
- **New pure `mobile/src/roofSketchAck.js`:** `applySketchAck({draft, ackGeneration, serverValue})` → Case 1 (draft gen == ack) retires that exact draft + caches the Office sketch; Case 2 (draft gen > ack, newer B) preserves B's document + generation, advances ONLY B's base/`document_version` to the server version, requeues B's `expected_version`, leaves B pending (never resurrects A). Plus `guardVersionFloor` + `reconcileDraftWrite` (monotonic generation + CAS floor — a late older write can't clobber newer, and version never regresses).
- **Coordinator reverse-race guard:** `createSketchSyncCoordinator` gained `noteServerVersion(rev,struct,v)` + a per-structure floor so `stage()` can never queue an `expected_version` below a known server version (B staged with stale v5 after ack→6 is floored to 6).
- **Wired into `sync.js`:** after `processQueue`/`saveMutationIfCurrent`, `_reconcileSketchAcks(processed)` applies the decision for each synced `measurement_sketch_update` with `serverValue` (caches server detail, retires or advances the draft, and bumps the still-pending B row's `expected_version`). Superseded A's SYNCED writeback is already a no-op via existing generation supersession → B stays pending for the existing rerun.
- **Boundary (B3B2/B3C NOT started):** no 409 conflict UI, no Use-Server/Keep-Local, no live lock, no AppState/background, no Phase C, no graph merge.
- **Verification:** NEW `roof_sketch_ack.node.test.js` **10** (matched retire+cache; Save(A)+Edit(B)→A-ack preserves B/advances 5→6/keeps pending; A can't overwrite/resurrect B; reverse race B-after-ack floored 5→6; monotonic+floor draft write; B succeeds v7 retires; House/Garage independent; full release example A5→B→A6→B6→B7 zero loss). Full mobile test:sketch (…/sync16/**ack10**) + measurements + transport PASS; photo/queue/cache PASS; Expo parse OK (incl. sync.js); CI push+pull_request include ack module + test. No new dependency; `mobile/package-lock.json` unchanged; no `mobile/yarn.lock`.
- **Files:** NEW `mobile/src/roofSketchAck.js`, `mobile/src/tests/roof_sketch_ack.node.test.js`; MODIFIED `mobile/src/sync.js`, `roofSketchSyncCoordinator.js`, `package.json`, `.github/workflows/roof-takeoff-contract.yml`.


## Task 6 Phase B3A correction — stage the EXACT committed/durable CAS state (2026-06) — DONE LOCALLY; no git ops
Fixed authoritative staging that read the visual document instead of the controller's committed CAS state.
- **Controller getters:** `documentVersion` (CAS token, from initial — not the sketch JSON), `authoritativeSnapshot()` = `{document: history.present (COMMITTED, never a preview), documentVersion, editMode, editGeneration}`, `isGenerationDurable(gen)` = `persistError===null && lastPersistedGeneration>=gen`.
- **Shared adapter `WIRE.stageFromController(editor, coordinator, {revisionId, structureId})`** (used by BOTH `RoofSketch.js` and contracts): captures the authoritative snapshot, drains persistence, and stages ONLY if that exact captured generation is durable — so Save(A)+Edit(B) can't stage B until B itself is durable; body `expected_version` comes from the controller's `documentVersion` (7→7, fresh→0), not `editor.document.document_version`.
- **`RoofSketch.js`:** `stageNow()` now calls `WIRE.stageFromController` (no reads of mutable visual state).
- **Verification:** B3A sync-staging grew 11→**16** (adds: version-7→expected_version:7, fresh→0, autosave-during-drag stages committed doc not preview, non-durable B not staged, B stages once durable — all via the real controller snapshot logic). Full mobile test:sketch (editor44/live-wiring36/sync**16**/…) + measurements + transport PASS; photo 6/2/2 + queue race + sketch_cache PASS; Expo parse OK. Only `roofSketchFieldController.js`, `roofSketchFieldWiring.js`, `screens/RoofSketch.js`, `tests/roof_sketch_sync_stage.node.test.js` changed; shared/Office untouched; no new dependency; `mobile/package-lock.json` unchanged; no `mobile/yarn.lock`.
- **Boundary:** B3B+ NOT started (no ack/draft-retirement, no CAS rebase after success, no 409 UI, no live lock, no Phase C).


## Task 6 Phase B3A — connect Field Roof Sketch to the existing sync queue (2026-06) — DONE LOCALLY; no git ops
Staged committed Field sketch edits into the EXISTING durable mutation queue (no new sync/retry engine). Reuses the deterministic identity `measurement-sketch-update:<rev>:<struct>`, `PUT /api/mobile/measurements/{rev}/sketches/{struct}`, and `queueMutation()`.
- **New `mobile/src/roofSketchSyncCoordinator.js`** (`createSketchSyncCoordinator`): requires local durability first, deep-clones + **freezes** the committed document snapshot, dedupes the same `edit_generation`, builds the shared `sketchUpdateMutation`, and calls the existing `queueMutation` (coalesces by shared clientId → newest generation wins). `local_edit_generation` is queue-only metadata, never in the request body.
- **`queue.js`:** `makeMutation` now carries `local_edit_generation` (metadata, not body); `processMutation` retains the full response as `serverValue` on HTTP 200/201 (for B3B). Body still `{schema_version, edit_mode, document, expected_version}` — no edit_generation.
- **`RoofSketch.js`:** added a **Save Sketch** action + debounced (~800ms) auto-stage on committed edits only (not previews/pan/zoom/selection); staging goes through `stageNow()` which requires `editor.flush().ok` before queueing.
- **B3A boundary (intentionally deferred to B3B):** local draft is NOT cleared on server success; editor `document_version` is NOT rebased; no 409/CAS/ack-retirement/live-lock/AppState work.
- **Verification:** NEW `roof_sketch_sync_stage.node.test.js` **11** (identity/version/mode capture, no edit_generation in body, local_edit_generation metadata, frozen snapshot, durability-first, dedupe, gen-B-supersedes-A, structure independence, offline pending, HTTP200 serverValue retained, draft NOT cleared). Full mobile test:sketch (editor44/live-wiring36/**sync11**/cache15/queue-race+clean-ts) + measurements + transport PASS; photo 6/2/2 PASS; shared 26/31/10/128; Office commands18/delegation22/topology63 PASS; Expo parse OK; CI push+pull_request paths include coordinator + new test. No new dependency; `mobile/package-lock.json` unchanged; no `mobile/yarn.lock`.
- **Files:** NEW `mobile/src/roofSketchSyncCoordinator.js`, `mobile/src/tests/roof_sketch_sync_stage.node.test.js`; MODIFIED `mobile/src/queue.js`, `screens/RoofSketch.js`, `package.json`, `.github/workflows/roof-takeoff-contract.yml`.
- **Status:** B3A COMPLETE LOCALLY; B3B NOT started.


## Task 6 Phase B2A FINAL closure — truthful pending status + permanent CI triggers (2026-06) — DONE LOCALLY; no git ops
- **Truthful pending save status:** added pure `WIRE.localSaveStatus(result)` (error/!ok→"Could not save on device"; ok&&pending→"Saving on device…"; ok&&!pending→"Saved on device") and made `RoofSketch.js` `settle()` + `retrySave()` BOTH use it (no more mapping every `!ok` to failure, and never "Saved" while a newer generation drains). Updated the controller `flush()` comment to document `ok`=no-error, `pending`=still-draining.
- **CI path triggers:** added all 10 Field runtime modules (App.js, roofSketchFieldController/Wiring/View, screens/RoofSketch, components/RoofSketchCanvas+SketchInspector, tests roof_sketch_editor/view/live_wiring) to BOTH `on.push.paths` and `on.pull_request.paths` (existing paths preserved; mobile-contract job + `test:sketch` chain unchanged). YAML validated.
- **Contracts:** live-wiring grew 31→**36** — Save(A)+Edit(B) now also asserts `resA.pending===true` + `localSaveStatus(resA)==="Saving on device…"`, `resB.pending===false` + `"Saved on device"`, and failure→"Could not save on device".
- **Verification:** mobile test:sketch (…/viewport13/editor44/live-wiring36), test:measurements, test:transport PASS; photo 6/2/2 + queue race + sketch_cache PASS; Expo parse 9/9; push+pull_request paths include all Field modules (0 missing). No new dependency; `mobile/package-lock.json` unchanged; no `mobile/yarn.lock`.
- **Files:** MODIFIED `.github/workflows/roof-takeoff-contract.yml`, `mobile/src/roofSketchFieldWiring.js`, `roofSketchFieldController.js`, `screens/RoofSketch.js`, `tests/roof_sketch_live_wiring.node.test.js`.
- **Status:** B2A COMPLETE LOCALLY — awaiting published exact-SHA verification.


## Task 6 Phase B2A — 2nd correction (4 live-state defects) (2026-06) — FIXED & CONTRACT-COVERED; no git ops
Independent review found 4 additional live-state defects; all fixed with contracts that actually assert the corrected behavior.
- **1. Combined pinch+pan focal continuity:** rewrote `applyTwoTouchView` so the model point under the ORIGINAL midpoint lands under the NEW midpoint at the new scale (`ns=clamp(scale*ratio)`, `t=nowMid - modelUnderPrevMid*ns`). Contract now verifies `modelToScreen(modelUnderPrev, result)===nowMid` (not just `scale===2`).
- **2. Drag preview survival:** a second finger during a vertex/penetration drag, and `onPanResponderTerminate` (interrupted gesture), now `restore()` the uncommitted preview and clear the drag — no moved-but-unsaved geometry can leak into a later commit. Contract: preview→restore leaves committed doc identity, no generation bump, zero durable writes.
- **3. Inspector cross-object state bleed:** `EdgeBody`/`FacetBody`/`VertexBody`/`PenBody` are now keyed by the selected id (`edge-${id}` etc.), so `confirmText`/`calibText`/`joinPending`/label state resets per object (no wrong-object edit path).
- **4. False "Could not save on device":** `flush().ok` now reflects DURABILITY/error only (`persistError===null`) plus a separate `pending` flag; a newer generation still draining is no longer a failure. Contract: Save(A)+Edit(B) where A's flush resolves while B pending → `ok:true, error:null`.
- **Verification:** live-wiring suite grew 28→**31**; mobile test:sketch (core26/topo31/edge10/cache15/queue11+8/viewport13/editor44/live-wiring31) + test:measurements + test:transport PASS; shared 26/31/10/128; photo+queue+cache PASS; Expo parse 9/9. No Office/frontend source touched this pass. Package: no new dependency; `mobile/package-lock.json` unchanged; no `mobile/yarn.lock`.
- **Files:** MODIFIED `mobile/src/roofSketchFieldWiring.js`, `roofSketchFieldController.js`, `components/RoofSketchCanvas.js`, `components/SketchInspector.js`, `tests/roof_sketch_live_wiring.node.test.js`.


## Task 6 Phase B2A FINAL — Field live-wiring & data-integrity closure (2026-06) — COMPLETE & LOCALLY GREEN; no git ops
Fixed the 15 integration defects found in the B2A React Native wiring (architecture preserved; not a rewrite). Extracted pure adapters in `mobile/src/roofSketchFieldWiring.js` that BOTH the screen/canvas and contracts call, so tests exercise real integration paths.
- **Load (§1):** screen now resolves the read-through cache envelope `{data,stale,cachedAt,error}` via `WIRE.resolveFieldSketchLoad` (server=`sketchResult.data`), retaining stale/cachedAt/error for status. **Identity (§2):** `WIRE.makeFieldEditorArgs` maps `revision_id→revisionId`, `structure_id→structureId` (controller naming unchanged). **Facet label data-loss (§3):** removed `getDocSafe()`; `FacetBody` receives the real `doc` and uses `onCommit((d)=>RS.setFacetLabel(d,id,label))`. **Manual polygon (§4)/connected facet (§5,§6):** canvas emits parent-visible `manual_build`/`facet_build` state; screen renders Create Polygon/Create Facet + Cancel; finalize goes through `WIRE.commitManualCreate`/`commitFacetCreate` which reject via the `validateMutation` gate (open loop / duplicate / non-positive) and preserve the original doc; an explicit `resetToken` clears transient build/draw state on create/cancel/tool/mode change.
- **Touch (§7,§8,§9):** pointer-up uses the SYNCHRONOUS `gesture.snapCandidate` (`WIRE.pickReleaseCandidate`), never React state; tap-vs-drag uses an 8px screen threshold (`WIRE.movedBeyondThreshold`) so a tap selects without any mutation/history/generation/persist; read-only now allows Select+Inspect+Pan (mutations disabled). **Two-finger (§10):** `WIRE.applyTwoTouchView` pans by midpoint delta + zooms by distance ratio (constant separation = pure pan). **Errors (§11):** canvas emits reason codes; screen `humanReason` owns copy. **Join (§12):** `WIRE.attemptJoin` surfaces `needsType` for classified conflicts → inspector shows result-type chips; other failures show a reason.
- **Durability (§13,§14,§15):** added `saveSketchDraftStrict` (propagates storage errors) used by the screen; controller records `persistError`, keeps the in-memory doc, doesn't poison the serialized chain, exposes truthful `flush()→{ok,...}` + `retry()`. Status is honest: "Saving on device…" → "Saved on device" or "Could not save on device" + Retry. Network boundary unchanged (no PUT/ack/409 — B3).
- **Files:** NEW `mobile/src/roofSketchFieldWiring.js`, `mobile/src/tests/roof_sketch_live_wiring.node.test.js`; MODIFIED `mobile/src/cache.js`, `roofSketchFieldController.js`, `components/RoofSketchCanvas.js`, `components/SketchInspector.js`, `screens/RoofSketch.js`, `package.json`, `.github/workflows/roof-takeoff-contract.yml`.
- **Verification (all Node contracts + parse green; device walkthrough NOT runnable in-pod):** Field editor **44** + viewport **13** + NEW live-wiring **28**; mobile test:sketch/measurements/transport PASS; shared 26/31/10/128; Office 9-suite (18/18/19/29/24/39/36/63/22) + `CI=false yarn build` PASS; photo 6/2/2 + queue race + sketch_cache PASS; Expo babel parse 9/9. Package: no new dependency; `mobile/package-lock.json` unchanged; NO `mobile/yarn.lock` (`frontend/yarn.lock` change is from the earlier react-router fix).
- **Status:** Plan 1 Task 6 NOT COMPLETE. B1A COMPLETE, B1B COMPLETE, **B2A COMPLETE**. Remaining: B3 authoritative Field save/conflict/live read-only hardening; Phase C measurement mapping/proposal reconciliation.


## Task 6 Phase B2A — Field Roof Sketch live UI + touch editor + local draft (2026-06) — COMPLETE & LOCALLY GREEN; no git ops
Built the first real Field/Mobile Roof Sketch UI, consuming the authoritative `@roofspan/roof-sketch-core` directly (zero mobile geometry/topology/history algorithms). Measurements → persisted Structure → **Sketch Roof** → RoofSketch screen → RN-SVG touch editor. B2A persists to the LOCAL device draft only (no authoritative PUT / no ack-clear / no 409 — those are B3).
- **New files:** `mobile/src/roofSketchFieldController.js` (pure controller: local-draft-authoritative load resolution, ONE commit path + ONE preview path, edit-generation bookkeeping, serialized local-draft write chain — persistence injected), `mobile/src/roofSketchView.js` (pure viewport math: model↔screen, zoomAround focal, pan, clamp, midpoint/distance, fitToViewport — never mutates the doc), `mobile/src/components/RoofSketchCanvas.js` (RN + react-native-svg: tap/drag/pan/pinch via PanResponder, live snap markers green/cyan/red, draw chain, facet-edge picking, penetration place/drag, edge dimensions + locked 🔒/discrepancy, validation shading), `mobile/src/components/SketchInspector.js` (edge type/confirmed/lock/calibrate/join/delete, facet label/pitch/orientation/delete, vertex delete, penetration type/delete), `mobile/src/screens/RoofSketch.js` (orchestrator: tools Select/Draw/Facet/Roof-feature/Pan, Connected/Manual toggle, undo/redo, validation panel, on-device status, read-only gate), tests `roof_sketch_editor.node.test.js` (44) + `roof_sketch_view.node.test.js` (13).
- **Wiring:** `App.js` registers `RoofSketch` after `Measurements` in BOTH LeadStack & MapStack. `Measurements.js` shows **Sketch Roof** per structure, gated on `existing?.id && st.id` (never `st.ref`); temporary structures show the "Save the measurement first…" hint. Navigates with `{revision_id, structure_id, structure_name, editable}` only.
- **Load rule:** local draft WINS over server sketch (never auto-cleared in B2A); else normalized server/cached; else fresh `createSketchDocument`. Status label is "Saved on device" (never "Synced").
- **Verification (all green, Node contracts + parse — device walkthrough NOT runnable in-pod):** mobile `test:sketch` (core 26 / topology 31 / edge_authority 10 / sketch_cache 15 / sketch_queue_race + clean-timestamp / **roof_sketch_view 13** / **roof_sketch_editor 44**), `test:measurements`, `test:transport` PASS. Shared `npm test` 26/31/10/128. Office 9-suite parity (commands18/mapping18/saveLifecycle19/saveCloseLifecycle29/proposalLifecycle24/geometryOps39/gestureOps36/topologyIntegrity63/sharedDelegation22) + `CI=false yarn build` PASS. Photo 6/2/2 + queue race + sketch_cache PASS. Expo babel parse 7/7 (RoofSketch/Canvas/Inspector/controller/view/App/Measurements). Static no-duplication check confirms the Field files define no shared algorithm.
- **CI:** mobile-contract job runs the new tests via `test:sketch`; Expo-parse list extended with the 5 Field files + App.js.
- **Package state:** no new dependency; `mobile/package-lock.json` unchanged; NO `mobile/yarn.lock`. (`frontend/yarn.lock` was modified by the earlier react-router reinstall fix, NOT by B2A.)
- **Status:** Plan 1 Task 6 NOT COMPLETE. B1A COMPLETE, B1B COMPLETE, **B2A COMPLETE**. Remaining: B3 authoritative Field save/durability/conflict/read-only hardening; Phase C measurement mapping/proposal reconciliation. Out of scope this pass (deferred): sketch PUT lifecycle, ack-clear, 409 UI, AppState flush, mapping/proposal/pending_accept, Plan 2.


## Task 6 Phase B1B — Office migrated to the shared engine (thin wrappers) + full parity gate (2026-06) — COMPLETE & LOCALLY GREEN; no git ops
Removed the temporary B1A duplication: the five Office roof-sketch algorithm files are now **thin ESM compatibility wrappers** that re-export (reference-preserving `export … from`) the authoritative engine in `@roofspan/roof-sketch-core`. There is now ONE editor engine, consumed by Office and ready for Field.
- **Wrappers (no local algorithm; existing Office import paths unchanged):** `commands.js` (41-name command surface), `snapping.js` (modelTolerance/snapTarget), `edgeDimensions.js` (edgeDimension/formatFeet), `gestures.js` (candidateFor/drawSnap/dragSnap/applyDrawPoint/applyVertexDrop), `historyCore.js` (legacy names push/pushFrom/undo/redo/canUndo/canRedo/makeHistory/MAX_HISTORY mapped onto shared history* exports). `RoofSketchCanvas.jsx`/`RoofSketchEditor.jsx`/`SketchInspector.jsx`/`ProposalPanel.jsx` and `saveLifecycle.js`/`proposalLifecycle.js`/`keyboardGate.js`/`history.js` were NOT modified.
- **New delegation contract** `__tests__/sharedDelegation.node.test.js` (**22 assertions**): proves reference-identity of every Office export to the shared package (commands 41, snapping 2, dimensions 2, gestures 5, history 8 legacy-name aliases), complete-surface presence, and a no-local-algorithm static check (each wrapper references the package and contains no `function`/`=>`/clone/pairKey). Wired into the CI `office-build` job after `topologyIntegrity`.
- **Parity gate (all green):** Office commands 18 / mapping 18 / saveLifecycle 19 / saveCloseLifecycle 29 / proposalLifecycle 24 / geometryOps 39 / gestureOps 36 / topologyIntegrity 63 / **sharedDelegation 22**. Shared `npm test` roofSketchCore 26 / topology 31 / edge_authority 10 / editor_engine 128 (0 failed/0 skipped). Office `CI=false yarn build` **PASS** (ESM↔CJS interop proven in the CRA production build; no new warnings, no roof-sketch import warnings). Mobile `npm ci` + `test:sketch`/`test:measurements`/`test:transport` PASS; sketch_queue_race (supersession 25 + orchestration 11 + clean-timestamp 8) + photo contracts 6/2/2 PASS. Shared core imports remain one-way (no react/frontend/mobile imports).
- **Note (§23):** `yarn install --frozen-lockfile` fails with pre-existing pod resolution drift ("lockfile needs to be updated") — UNRELATED to B1B (no `package.json`/`yarn.lock` change, no dependency added); the mandated production build passes.
- **Files:** MODIFIED `frontend/src/components/roof-sketch/{commands,snapping,edgeDimensions,gestures,historyCore}.js` + `.github/workflows/roof-takeoff-contract.yml`; NEW `frontend/src/components/roof-sketch/__tests__/sharedDelegation.node.test.js`. `frontend/yarn.lock` & `mobile/package-lock.json` unchanged; NO `mobile/yarn.lock`; NO new dependency; NO git ops.
- **Status:** Plan 1 Task 6 NOT COMPLETE. B1A COMPLETE; **B1B COMPLETE** — single authoritative engine = `@roofspan/roof-sketch-core`. Remaining: B2 Field live editor UI; B3 Field durability/conflict/read-only; Phase C mapping/proposal reconciliation. **Live licensed Office UI walkthrough NOT runnable in-pod** (needs a licensed session + saved structure) — covered by the deterministic parity suites; delegation is reference-identity so runtime behavior is unchanged by construction.


## Task 6 Phase B1A — Shared Roof Sketch Editor Engine (ADDITIVE ONLY) (2026-06) — COMPLETE & LOCALLY GREEN; no git ops
Promoted the approved Office editor logic into the shared `packages/roof-sketch-core` (CommonJS) so Office and Field can consume ONE engine. **ADDITIVE ONLY**: no Office frontend file was touched; Office still runs its own copy. Office→shared migration is intentionally deferred to B1B.
- **New shared modules (CommonJS, `require`/`module.exports`):** `editorCommands.js` (all pure commands + topology-safe ops: splitEdgeSafe/mergeVertices/insertExistingVertexIntoEdge/joinEdges, validateMutation gate, mapping/proposal/penetration/scale/lock helpers), `snapping.js` (modelTolerance/snapTarget), `edgeDimensions.js` (edgeDimension/formatFeet), `gestures.js` (candidateFor/drawSnap/dragSnap/applyDrawPoint/applyVertexDrop), `history.js` (undo/redo, MAX_HISTORY=100). All ported verbatim from the approved Office source; geometry/topology/validation math is reused from schema/geometry/topology/proposals (never re-implemented). Dep direction schema→geometry→topology→proposals→editorCommands→snapping→gestures; edgeDimensions←geometry; history standalone. No module requires index.js (no circular dep).
- **index.js expanded** with the full editor API (history exported as historyPush/PushFrom/Undo/Redo/CanUndo/CanRedo to avoid name clash); existing exports/semantics unchanged.
- **New contract suite** `test/editor_engine.node.test.js` (**128 assertions**, imports ONLY from `require("..")`): editor-command 25, proposal-decisions 2, mapping 7, safe-split 8 + shared 3, merge 18 (incl. all 4 protected self-loop kinds + degenerate-triangle reject returns original doc), insert 12, join 16 (incl. cyclic last→first + type resolution), mutation-validation 3, snap 7, gesture 12, dimension 8, history 7. Wired into the package `test` script → CI `sketch-core` job (`npm test`) now runs it automatically (no workflow edit needed).
- **Verification (all green):** package `npm test` = roofSketchCore 26 / topology 31 / edge_authority 10 / **editor_engine 128**. Office smoke UNCHANGED & passing: commands 18 / geometryOps 39 / gestureOps 36 / topologyIntegrity 63; Office `CI=false yarn build` PASS. Mobile `npm ci` PASS; `test:sketch` / `test:measurements` (edge-identity 4) / `test:transport` (8) PASS; expanded package resolves all 15 editor APIs from mobile node_modules; babel-preset-expo transform OK 6/6 (Metro-compatible). Photo contracts 6/2/2 + sketch_queue_race + clean-timestamp race all green.
- **Files:** NEW `packages/roof-sketch-core/{editorCommands,snapping,edgeDimensions,gestures,history}.js` + `test/editor_engine.node.test.js`; MODIFIED `packages/roof-sketch-core/{index.js,package.json}`. Removed stray untracked `mobile/yarn.lock` (repo uses package-lock.json). `frontend/yarn.lock` & `mobile/package-lock.json` unchanged; NO new dependency; NO git ops.
- **Status:** Plan 1 Task 6 NOT COMPLETE. Phase B1A COMPLETE. Office migration NOT STARTED (deferred to B1B). Remaining: B1B Office wrapper migration + full parity; B2 Field live editor UI; B3 Field durability/conflict/read-only; Phase C mapping/proposal reconciliation.


## Task 6 Phase B — Pass 3: Clean-Timestamp Race Micro-Correction (Part 0) (2026-06) — CODE COMPLETE & GREEN; no git ops
Closed the last queue-completion race (spec §0/§41). The Field editor core (Parts 1–50) is **NOT implemented this pass** (context-budget); no partial screens/canvas/inspector or App.js edits were introduced, so the mobile bundle stays healthy. **Task 6 remains NOT COMPLETE.**
- **Atomic clean marker:** new `storage.markCleanIfNoPending(cacheKey, value)` runs the pending-count check + `last_sync_at` write inside the SAME `_serialize` critical section as `enqueue`, so a mutation B enqueued concurrently can never slip between the clean check and the marker write. `sync._markSynced` now delegates to it (returns false when work exists → no false clean; `_rerunRequested` still drives B's follow-up pass).
- **Delete paths serialized:** `removeMutation` / `removeFailedMutations` now run through `_serialize` too, so recovery/delete can't undermine the guarantee.
- **Tests:** appended a dedicated CLEAN-TIMESTAMP RACE section (8 assertions) to `mobile/src/tests/sketch_queue_race.node.test.js` (now 25 race + 11 orchestration + 8 clean-timestamp), proving B-between-check-and-marker keeps `last_sync` unchanged, B pending, follow-up requested, and no false-clean once B exists.
- **No regression:** `test:sketch` all green; `test:transport` 8; `test:measurements` green; photo contracts 10 ok/0 not-ok; Expo Babel parse OK for storage.js/sync.js. `test:sync` still needs a live Office backend (not runnable in pod).
- Files: `mobile/src/storage.js`, `mobile/src/sync.js`, `mobile/src/tests/sketch_queue_race.node.test.js`.
- **REMAINING Task 6 (Phase B core + Phase C):** shared editor-op promotion into `roof-sketch-core` (+ Office regression/build); `RoofSketch.js` + Lead/Map stack registration; Measurements "Sketch Roof" entry (persisted-id gate); `RoofSketchCanvas.js` (RN-SVG tap/drag/pan/pinch, snap, split+chain, merge, insert, join, manual, facet, penetration, undo/redo); `SketchInspector.js`; calibration/dimension/confirm-lock UI; durable autosave/crash-recovery + lifecycle flush wiring; explicit Save; conflict + read-only UI; Field editor/recovery Node contracts; Expo parse of new screens; then Phase C mapping/proposal reconciliation.


## Task 6 Phase B — Pass 2: Queue Supersession FINAL Closure (Part A) (2026-06) — CODE COMPLETE & LOCALLY GREEN; no git ops
Closed the remaining queue races found in independent review (spec §A1–A14). Self-contained, atomic, no Office/photo regression. The Field editor UI (Parts B–W) is **NOT implemented this pass** (context-budget); the mobile app bundle is unchanged (no half-wired screens/App.js).
- **Atomic result writeback (§A6/§A7):** `storage.saveMutationIfCurrent` is now a single conditional `UPDATE ... WHERE client_id=? AND COALESCE(mutation_generation,1)=?` and applies only when `changes>0`; it never inserts a missing row (a late result cannot resurrect a removed mutation). Legacy NULL generation treated as 1 (§A8).
- **Atomic same-client bump (§A9):** `enqueue` uses an `INSERT ... ON CONFLICT(client_id) DO UPDATE SET mutation_generation=COALESCE(...,1)+1` UPSERT plus a serialized write chain, so overlapping enqueues get strictly-increasing unique generations; returns the durable stamped row (§A10, `queueMutation` returns it).
- **Rerun + authoritative completion (§A1–A5):** `runSync` keeps single-flight but sets `_rerunRequested` when work is queued mid-flight and reruns in `finally`; completion (`last_sync_at`/markSynced) is decided from a fresh `loadAllMutations()` (current storage), never the stale `processed[]`. A superseded newer mutation keeps the queue non-synced and auto-sends on the next pass.
- **Tests:** `mobile/src/tests/sketch_queue_race.node.test.js` now 25 supersession/coalescing/recovery + **11 orchestration** assertions (A11–A13, W5–W7: A success/409/500 can't overwrite/downgrade B; B auto-sends; last_sync gated; concurrent enqueue generations unique/increasing). All green.
- **No regression:** `test:sketch` (core 26 / topology 31 / edge_authority 10 / sketch_cache 15 / race+orchestration 36) green; `test:transport` 8; `test:measurements` green; photo contracts 10 ok/0 not-ok. Expo Babel parse OK for queue/storage/sync/sketchCache. `test:sync` needs a live Office backend (404 here — not runnable in pod).
- Files: `mobile/src/storage.js`, `mobile/src/sync.js`, `mobile/src/queue.js` (unchanged from Pass 1 helpers), `mobile/src/sketchCache.js`, `mobile/src/tests/sketch_queue_race.node.test.js`. `mobile/yarn.lock` was auto-generated Pass 1 (no dep added).
- **REMAINING Task 6 (Phase B unfinished + Phase C):** shared editor-op promotion into `roof-sketch-core`; `RoofSketch.js` screen + LeadStack/MapStack registration; `RoofSketchCanvas.js` (RN-SVG touch: draw/pan/pinch/snap/split/merge/insert/join/manual/facet/penetration/undo-redo); `SketchInspector.js`; Measurements "Sketch Roof" entry; calibration/dimension/confirm-lock UI; structure-scoped mapping + proposal pending_accept; local autosave/crash-recovery UI wiring; conflict + read-only UI; Field editor/recovery Node contracts; Office regression after promotion; live walkthrough.


## Task 6 (Field Roof Sketch Editor) — Pass 1: Offline-Safety Foundation (Parts 18–22) (2026-06) — CODE COMPLETE & LOCALLY GREEN; no git ops
Delivered the release-blocker offline-safety core first (self-contained, headless-testable, cannot regress Office/photo). The Field editor UI (screens/canvas/inspector), shared-engine promotion, mapping/proposal UI, calibration UI and the live Expo walkthrough are **NOT yet implemented** in this pass (context-budget limit) — the mobile app still bundles unchanged (all edits are additive to non-UI modules).
- **Queue mutation-generation supersession (§20, release blocker):** `queue.js` adds `mutation_generation` (+ pure `nextGeneration`/`shouldApplyResult`/`stampGeneration`); `storage.js` adds an **additive** `mutation_generation` column, a generation-bumping `enqueue`, a plain `saveMutation`, and a generation-guarded `saveMutationIfCurrent`; `sync.js` writeback now uses `saveMutationIfCurrent`. An older in-flight result (success OR 409) can no longer overwrite a newer queued edit of the same structure; removed rows can't be resurrected.
- **Coalescing / independence (§19):** `sketchCache.sketchUpdateMutation` builds the deterministic PUT with a structure-stable `client_id`; repeated saves coalesce to one row with the latest document; different structures stay independent.
- **Crash-safe autosave ordering (§18):** draft gains `edit_generation` + pure `shouldPersistDraft` (older async write can't clobber a newer generation). Save(A)+Edit(B) keeps B local after A acks.
- **Tests:** NEW `mobile/src/tests/sketch_queue_race.node.test.js` (25 assertions) wired into `npm run test:sketch` and the CI path filter. `test:sketch` = core 26 / topology 31 / edge_authority 10 / sketch_cache 15 / **sketch_queue_race 25** all green. `test:transport` 8 green; `test:measurements` green. `test:sync` needs a live Office backend (404 here — NOT runnable in this pod; unrelated to these additive changes).
- Files: `mobile/src/queue.js`, `mobile/src/storage.js`, `mobile/src/sketchCache.js`, `mobile/src/sync.js`, `mobile/src/tests/sketch_queue_race.node.test.js`, `mobile/package.json`, `.github/workflows/roof-takeoff-contract.yml`. A `mobile/yarn.lock` was auto-generated by tooling (none existed before; no dependency added). **Remaining Task 6 parts to build next:** shared editor-op promotion into `roof-sketch-core`, `RoofSketch.js`/`RoofSketchCanvas.js`/`SketchInspector.js`, Measurements "Sketch Roof" entry + stack registration, mapping/proposal/calibration UI, conflict/read-only UI, editor & recovery Node contracts, Expo Babel parse.


## Task 4 Phase 3 FINAL Topology Integrity Closure (2026-06) — CODE COMPLETE & LOCALLY GREEN; no git ops
Closed the graph-integrity holes found in independent review of the published Phase 3. No editor redesign.
- **mergeVertices:** removed self-loop edges are now dropped from `facet.edgeIds` (cyclic consecutive-dupe collapse) → valid triangle from a rectangle, never `broken_edge_reference`; protected self-loop collapse rejected (`protected_edge_collapse`, 4 states); affected connected facets get `vertexIds: []`; stale graph decisions dropped for removed AND rewired (endpoint-changed) incident edges (relational MeasurementEdge UUIDs preserved).
- **insertExistingVertexIntoEdge:** pre-checks both child pairs against existing edges → rejects `duplicate_edge_creation` (original unchanged); invalidates decisions for the replaced target + every incident edge whose geometry moved.
- **Free vertex move commit:** `moveVertexFinal` invalidates incident graph decisions on pointer-up only (preview still silent).
- **Safety gate:** new pure `validateMutation(before, after)` (uses shared-core `validateSketch` only) gates merge/insert/split/join; a mutation that would introduce a NEW hard error is rejected and returns the original doc (`facet_would_be_invalid`). Degenerate triangle merge rejected via this gate.
- **Shared core:** `validateSketch` now hard-fails `duplicate_edge` (unordered endpoint key) in connected_graph mode (manual unchanged).
- **Canvas/Inspector:** double-click split disabled in manual_polygon; reject-reason toasts (protected / duplicate / invalid); Inspector protected wording now says "Mapped, confirmed, or locked edge — clear the confirmed length and/or unmap/unlock…". Live snap wiring + LF authority (edgeGeometryLengthFeet) + geometry−confirmed direction preserved.
- **Tests (all green):** Office commands 18 / mapping 18 / saveLifecycle 19 / saveCloseLifecycle 29 / proposalLifecycle 24 / geometryOps 39 / gestureOps 36 / **topologyIntegrity 63 (NEW)**; shared core roofSketchCore 26 / **topology 31** / edge_authority 10. `CI=false yarn build` OK; `frontend/yarn.lock` unchanged. CI office-build step now also runs topologyIntegrity. Files: `commands.js`, `gestures.js`, `RoofSketchCanvas.jsx`, `SketchInspector.jsx`, `packages/roof-sketch-core/topology.js`, `__tests__/topologyIntegrity.node.test.js`, `packages/roof-sketch-core/test/topology.node.test.js`, `.github/workflows/roof-takeoff-contract.yml`. **Live licensed Office walkthrough: NOT runnable here** (needs licensed session + saved structure).


## Marketing Website — SEO Expansion (multi-page, structured data, sitemap, analytics) (2026-06) — COMPLETE & LOCALLY GREEN; no git ops
Expanded `roofspan-website` (Next.js 14 static export) from a single page into a crawlable multi-page site.
Canonical host standardized to `https://roofspan.io` (no www). Only verified RoofSpan capabilities described.
- **New pages (App Router, each: unique title/description, canonical, OG, one H1, breadcrumbs, WebPage+BreadcrumbList JSON-LD, CTA, internal links):** /roofing-crm-software/, /roofing-canvassing-software/, /roofing-territory-management/, /roofing-field-sales-software/, /roofing-property-intelligence/, /abc-supply-integration/ (FAQPage + honest "not an official/certified ABC partner" note), /roofing-job-management-software/, /roofing-software-pricing/ (reuses seat calculator), /about/, /contact/, /resources/ + 6 articles under /resources/[slug]/.
- **Homepage:** title "Roofing CRM & Canvassing Software | RoofSpan"; required meta description; internal links from BigThree/Product/MobileArea/ABC sections to the dedicated pages (no longer anchor-only). FAQPage + WebPage JSON-LD moved to homepage; Organization/SoftwareApplication/WebSite global in layout.
- **Technical SEO:** `app/sitemap.js` + `app/robots.js` (replaced static public files; canonical host), `app/not-found.jsx` (branded 404, noindex → out/404.html served with HTTP 404), real `public/favicon.ico` (PNG-in-ICO) + icon metadata, env-driven Google/Bing verification.
- **Analytics:** env-only GA4/GTM (`NEXT_PUBLIC_GA_MEASUREMENT_ID`/`NEXT_PUBLIC_GTM_ID`, no hard-coded IDs) via `components/Analytics.jsx` + `src/analytics.trackEvent`; events wired for header/hero/pricing/product CTAs, walkthrough, resource clicks, early-access submit.
- **Perf:** hero image eager+fetchPriority, below-the-fold images lazy with width/height (no CLS), fonts already self-hosted via next/font.
- **Tests:** new `__tests__/seo.test.jsx` (metadata/canonical/uniqueness/JSON-LD/sitemap/robots/favicon/404/no-fake-review); `jest.setup.js` IntersectionObserver polyfill; e2e rewritten (nav→pages, commercial page JSON-LD, resources, sitemap/robots/favicon 200, 404). Results: lint clean, Jest **53/53**, Playwright **6/6**, build 23 pages, 601 internal links OK, 0 console errors (desktop+mobile).
- **Owner-only (not code):** Search Console/Bing account verification, directory/backlink/review/testimonial building, pasting GA4/GTM + verification env values. **Git:** user publishes via Save to GitHub (agent does not push).


## Task 4 Phase 3 Part A — Live Snap Gestures WIRED + closure corrections (2026-06) — CODE COMPLETE & LOCALLY GREEN; no git ops
Completed the previously DEFERRED live canvas pointer-gesture wiring. Topology math stays pure; the React
canvas is a thin coordinator. New pure `gestures.js` + `insertExistingVertexIntoEdge` command.

- **Live draw snap markers:** `RoofSketchCanvas` hover uses the canonical `snapTarget` (via `gestures.drawSnap`)
  with true screen-space tolerance (`modelTolerance(snapPx, view.k)`). Non-interactive markers: green ring
  = vertex candidate, cyan dot = edge candidate, red ✕ ring = protected/blocked. `data-testid="snap-marker"`.
- **Draw-to-edge split + chain:** connected-mode Draw drops onto an edge interior → `splitEdgeSafe` + chain in
  ONE `ctl.run` history entry. Direct SVG edge clicks in connected Draw route through the SAME flow (`drawAt`).
  Manual polygon draw unchanged (vertex/free only, never splits).
- **Vertex-drag gestures (pointer-up = ONE mutation):** `gestures.applyVertexDrop` → vertex→vertex `mergeVertices`,
  vertex→edge-interior `insertExistingVertexIntoEdge` (projects onto segment, REUSES the dragged vertex id,
  splits the edge, updates every facet loop, preserves shared topology), free→plain `moveVertex`. Protected
  edge proximity = blocked candidate (never a free placement); a failed op restores the original doc unchanged.
  Dragged vertex's own incident edges are ineligible targets.
- **One-history-per-gesture:** new `ctl.previewSilent` updates the visible doc during pointer-move WITHOUT
  bumping the edit generation / adding history; the single commit happens on pointer-up via `commitFrom`.
- **Closure corrections verified/fixed:** `deriveProposals` edge LF now via shared `edgeGeometryLengthFeet`
  (single source); SketchInspector already used it; locked discrepancy = geometry − confirmed (+2 for 20 vs 18);
  one-sided protected duplicate-edge collapse rejected in `mergeVertices`; cyclic last→first join collapse;
  stale edge proposal decisions dropped after split/join/merge/insert; all graph ops blocked in manual_polygon.

**Contracts (all green):** office commands 18 / mapping 18 / saveLifecycle 19 / saveCloseLifecycle 29 /
proposalLifecycle 24 / geometryOps 39 / **gestureOps 36 (NEW)**. Shared core 26 / topology 28 / edge_authority 10.
Office `CI=false yarn build` OK. `frontend/yarn.lock` unchanged. CI `office-build` now also runs gestureOps.
Files changed: `RoofSketchCanvas.jsx`, `RoofSketchEditor.jsx`, `commands.js`, `packages/roof-sketch-core/proposals.js`,
`.github/workflows/roof-takeoff-contract.yml`; NEW `gestures.js`, `__tests__/gestureOps.node.test.js`.
**NOT runnable here:** live licensed Office E2E (app root needs a licensed session; canvas needs a saved
structure) — covered by the deterministic gesture/geometry contracts. **STOP** after local green (user publishes).


## Task 4 Phase 3 FINAL Closure — Geometry Integrity Fixes (2026-06) — PARTIAL: data-integrity defects fixed & green; live-gesture wiring DEFERRED
Fixed the pure data-integrity defects flagged in review. Live canvas pointer-gesture wiring is NOT done
this pass (documented below).
- #13 connected_graph guards on `splitEdgeSafe`/`mergeVertices`/`joinEdges` (reject `connected_graph_required`); Join control hidden + double-click split no-op in manual_polygon.
- #14 SketchInspector edge LF now derives from shared `edgeGeometryLengthFeet` (canvas already did). deriveProposals uses `distance*feetPerUnit` which is numerically identical — NOT refactored to the helper (low-risk equivalence, noted).
- #15 locked-edge discrepancy direction corrected to `geometry - confirmed` (+2 for 20 vs 18).
- #16 `mergeVertices` now rejects duplicate-edge collapse if EITHER edge is protected (`protected_duplicate_collapse`) — no one-sided metadata loss.
- #17 duplicate collapse type resolution is order-independent (keeps the classification; rejects two different classifications).
- #19 `joinEdges` facet-boundary replacement is now cyclic (last→first pair collapses to ONE joined edge).
- #20 join drops stale graph decisions for BOTH source edge ids. #28 protected messages mention confirmed length.

**Contracts green:** commands 18 / mapping 18 / saveLifecycle 19 / saveCloseLifecycle 29 / proposalLifecycle
24 / geometryOps **39** (adds manual-mode guards, protected-duplicate reject, discrepancy +2). Shared core
26/28/10. Office `CI=false yarn build` OK. `frontend/yarn.lock` unchanged.

**DEFERRED (NOT done this pass, budget):** live canvas pointer-gesture wiring in RoofSketchCanvas
(#1–#12): snapping.js live draw snap markers, direct-edge-click routing, draw-to-edge interior split
gesture, vertex-drag→merge and vertex-drag→edge-insert on pointer-up, drag-preview edit-generation
suppression; the `insertExistingVertexIntoEdge` command (#7); and the live-gesture/history interaction
contracts (#22–#27 for gestures). The underlying pure engine (splitEdgeSafe/mergeVertices/joinEdges/
snapping/edgeDimensions) is complete and contract-tested. LIVE OFFICE WALKTHROUGH: NOT RUNNABLE HERE.


## Task 4 Phase 3 — Canvas Geometry Closure (2026-06) — CODE COMPLETE (engine+contracts+partial UI) & LOCALLY GREEN; no git ops
Final Office canvas geometry engine + deterministic contracts. Geometry stays authoritative in
`@roofspan/roof-sketch-core`; editor commands stay pure.

**Shared core:** `projectPointToSegment(point,a,b)` (clamped t, distance, zero-length safe) and
`edgeGeometryLengthFeet(doc,edge)` (single source for edge LF; null when unscaled) — exported from the
package.
**Pure topology commands (commands.js, all return `{ok,doc,reason?}`):** `edgeIsProtected`;
`splitEdgeSafe` (projects onto the segment, refuses protected edges + near-endpoint reuse, updates EVERY
facet loop preserving direction, strips stale edge decisions); `mergeVertices` (rewire, drop self-loops,
compatible-only duplicate collapse, reject incompatible); `joinEdges` (single shared vertex, branch/facet/
duplicate-outer/protected guards, type inheritance + explicit `resultType` on conflict).
**Pure modules:** `snapping.js` (screen-space `modelTolerance`, deterministic priority vertex>edge>free,
projection-on-segment only) and `edgeDimensions.js` (locked confirmed value wins; exposes geometry +
discrepancy; uses shared-core length).
**UI wired:** RoofSketchCanvas renders LF dimension labels (midpoint + perpendicular offset, non-scaling,
🔒 + discrepancy tooltip for locked, unscaled cue instead of fake LF) and double-click split now uses
`splitEdgeSafe` (projected + protected-block toast, atomic one-step history). SketchInspector has a Join Edge
control (adjacent-only candidates, conflict→required result-type, protected/none states). Editor `cmd.join`
commits atomically + selects the result.
**Contracts (CI office-build, 6 files):** commands 18 / mapping 18 / saveLifecycle 19 / saveCloseLifecycle
29 / proposalLifecycle 24 / **geometryOps 38** (projection matrix, shared length==proposal source, basic+
projected split, endpoint reuse, all-4 protected-split blocks, shared-facet split, merge + incompatible
reject, join simple/type-resolution/branch-reject/protected, snap priority/nearest/free, dimensions locked-
wins). Shared core 26/28/10.

**Local verification (green):** all above + office `CI=false yarn build` OK. `frontend/yarn.lock` unchanged.
Backend/mobile/photo systems untouched this pass.
**NOT wired this pass (engine-only, honest scope):** live canvas POINTER gestures for interior draw-to-edge
snap markers and vertex-drag→edge/vertex merge-on-pointer-up (the pure `snapping.js`/`mergeVertices` engine +
contracts are complete; only the RoofSketchCanvas pointer-move/up wiring is deferred). LIVE OFFICE
WALKTHROUGH: NOT RUNNABLE IN THIS ENVIRONMENT (no licensed session/browser).
**STOP** after local green (no git ops; user publishes). No Field editor / Plan 2.


## Task 4 Phase 2 FINAL Save/Close Race Closure (2026-06) — CODE COMPLETE & LOCALLY GREEN; no git ops (user publishes)
Closed the save/close concurrency defect on the approved Phase 2 editor. Architecture NOT rewritten.

- **One active sketch-save per editor:** `RoofSketchEditor` now drives all save-state transitions through a
  synchronous, ref-backed `commitSaveState` (updates `saveRef.current` AND React state in one path).
  `doSave()` opens with a HARD `SL.canBeginSave(saveRef.current)` guard → returns `{ok:false,
  reason:"already_saving"}` without preparing a second request or reusing the CAS version. `prepareSketchSave`
  (synchronous, detached `structuredClone` snapshot, real existing-sketch `expected_version`) preserved.
- **doSave returns `{ok, clean}`:** `clean = SL.isCleanState(next)` computed against the resolved ref-backed
  state — a newer edit made while Save(A) ran ⇒ `clean:false` (server version still retained,
  `lastPersistedGeneration`=A, `editGeneration`=A+B, dirty).
- **Save & Close never closes dirty:** `saveAndClose()` closes ONLY when `res.ok && res.clean`; otherwise
  keeps the editor open, preserves the newer edit, and warns "Save again before closing." Close button
  disabled while `save.saving`; modal buttons (Save & Close / Discard / Continue) disabled while `closing`.
- **True modal:** extracted pure `keyboardGate.resolveKey()` — while the unsaved-close confirmation is open,
  Ctrl+Z/Ctrl+Y/Ctrl+Shift+Z/Delete/Backspace are all swallowed (no geometry/history/selection mutation);
  Escape only dismisses the confirmation (ignored while a Save & Close is running).

**New pure helpers:** `SL.canBeginSave`, `SL.isCleanState`, `keyboardGate.js`.
**Contracts (CI office-build, now 5 files):** commands 18 / mapping 18 / saveLifecycle 19 / **saveCloseLifecycle
29** / proposalLifecycle 24. New file proves: second save rejected (no 2nd prepare, CAS used once), saveRef
saving-flag synchronous on begin/success/failure, Save(A)+Edit(B)→clean=false+open, clean Save&Close→close,
409/422/generic stay dirty, close blocked while saving, and the full modal keyboard-gate matrix.

**Local verification (all green):** office contracts 18/18/19/29/24; office `CI=false yarn build` OK.
`frontend/yarn.lock` unchanged. Files changed (5): `RoofSketchEditor.jsx`, `saveLifecycle.js`,
`keyboardGate.js` (new), `__tests__/saveCloseLifecycle.node.test.js` (new), `roof-takeoff-contract.yml`.
Backend/shared-core/mobile untouched this pass. **STOP** after local green per instruction (no git ops; user
publishes). Do NOT start Phase 3 / Field editor / Plan 2.


## Task 4 Phase 2 FINAL Closure Corrections (2026-06) — CODE COMPLETE & LOCALLY GREEN; CI push pending
Three integration defects fixed on top of the approved Phase 2 architecture (baseline main `02206393`, CI run
33204137410 green). Architecture NOT rewritten.

1. **Save-request preparation (BLOCKER):** `RoofSketchEditor.doSave()` previously captured `snapshotGeneration`/
   `expectedVersion` via side effects INSIDE a `setSave(prev=>…)` updater — unsafe React that could send
   `expected_version=undefined→null` for an existing sketch and get a false 409. Added pure
   `SL.prepareSketchSave(currentSaveState, currentDocument)` and a synced `saveRef`; `doSave` now prepares
   synchronously outside any updater and sends a `structuredClone` (detached) document snapshot.
2. **Finalization discovery failure:** `MeasurementWorksheet.finalizePending()` no longer silently returns when
   `listSketches` fails — it warns (measurement stays saved, proposals stay pending). Per-sketch CAS/422/error
   already warned via the `failed` counter.
3. **Invalid reopened pending target:** added `PL.canApplyPending(dec, validIdSet)`; the reopened-pending UI now
   disables "Apply to Worksheet Draft" and shows an invalid-mapping message for stale targets — never calls
   `onMeasurementChanged`, never dirties the Worksheet, never shows a false success, never silently redirects.

**New/extended contracts (CI office-build, all four run before Build Office UI):** saveLifecycle **19** (adds
prepareSketchSave: real CAS version for existing sketch / null for new, detached snapshot, edit-during-save
stays dirty); proposalLifecycle **24** (adds invalid pending facet+edge cannot Apply, no callback/no false
success); mapping **18**; commands **18**.

**Local verification (all green):** office contracts 18/18/19/24; office `CI=false yarn build` OK. Backend
(33) / shared core (26/28/10) / mobile (edge-identity 4, sketch-cache 15) unchanged this pass and remain
green. `frontend/yarn.lock` untouched. Files changed (6): `MeasurementWorksheet.jsx`, `RoofSketchEditor.jsx`,
`saveLifecycle.js`, `proposalLifecycle.js`, `__tests__/saveLifecycle.node.test.js`,
`__tests__/proposalLifecycle.node.test.js`. **PENDING:** user Save-to-GitHub → all 5 Roof Takeoff Contract
jobs green → STOP for independent review. Do NOT start Phase 3 / Field editor / Plan 2.


## Task 4 Closure Phase 2 — Mapping, Save Safety & Proposal Lifecycle (2026-06) — CODE COMPLETE & LOCALLY GREEN; CI push pending
Office Roof Sketch Editor state-integrity + proposal-workflow architecture. Frontend/state only (no backend
measurement-persistence redesign; Phase 1 reconciliation preserved). New deterministic pure modules are the
backbone and are wired into CI (office-build) before the build.

**New pure modules (Node-testable):**
- `scopeMeasurements.js` — structure-safe scoping: editor receives ONLY the facets/edges/penetrations owned
  by the current structure (edges via facet_id OR facet_id_secondary; never by type/length).
- `saveLifecycle.js` — generation-based dirty tracking (`editGeneration` vs `lastPersistedGeneration`), frozen
  snapshot save, 409/422/error preserve-local. Dirty is NEVER a "saved" string flag.
- `proposalLifecycle.js` — `acceptProposed` → worksheet draft change + `pending_accept` (never `accepted`);
  `finalizeAfterSave` promotes pending→accepted ONLY when the persisted authoritative value matches (tolerant
  compare); `keepCurrent`; `applyPendingToDraft`; editor-session `rollbackPlan` (restores original only when
  the field still equals the editor-applied value — later manual edits win); stale-mapping detection.
- `commands.js` — `setFacetMeasurementLink`/`setEdgeMeasurementLink` (one-to-one, no silent steal; edge keeps
  `measurement_edge_id`+`relational_edge_id` coherent), `setDecisions`.

**UI wiring:** SketchInspector gains scoped one-to-one facet & edge mapping dropdowns (Unmapped default,
used-ids disabled, invalid/stale mapping warning). ProposalPanel enforces the accept precondition (must be
mapped) and shows Pending/Accepted/Kept status. RoofSketchEditor uses the generation reducer + frozen
snapshot save, accept→pending_accept + session tracking, reopened-pending section (Apply to Worksheet Draft /
Keep Current, never auto-edits), and Discard rolls back only the editor's worksheet changes via the session.
MeasurementWorksheet scopes data into the editor, applies draft changes by relational id+metric, rolls back
on discard, and after a successful authoritative PUT finalizes pending→accepted via a second CAS sketch save
(measurement stays correct even if finalization fails).

**Contracts (CI-gated in office-build):** `mapping.node.test.js` (18), `saveLifecycle.node.test.js` (10),
`proposalLifecycle.node.test.js` (18), existing `commands.node.test.js` (18). Cover scoping, one-to-one
mapping + undo/redo, cross-structure exclusion, save-race (edit during in-flight save stays dirty), 409/422/
generic preserve-local, accept→pending, matching→accepted, mismatch/failure→pending, keep_current, reopen no
auto-edit, apply explicit, and session rollback (incl. later-manual-edit-wins + unrelated-edits-untouched).

**Local verification (all green):** shared core 26/28/10; office editor contracts 18/18/10/18; office
`CI=false yarn build` OK; backend 33 (incl. Phase 1 survival/clone/authz + measurement/takeoff/photo); mobile
edge-identity 4 + sketch-cache 15. NOT executed here: live licensed Office E2E (item 46) — covered by the
deterministic lifecycle contracts. **PENDING:** user Save-to-GitHub → all 5 Roof Takeoff Contract jobs green
on that SHA → STOP for independent review. Do NOT start Phase 3 (dimension labels/snapping/split/Join Edge)
or Field editor / Plan 2.


## Task 4 Phase 1 FINAL Closure Corrections (2026-06) — CODE COMPLETE & LOCALLY GREEN; CI push pending
Small correction pass on top of Phase 1 (baseline: GitHub main `884c414`, all 5 Roof Takeoff Contract
jobs green). Fixed one real integration defect + hardened the contract tests. Phase 1 reconciliation code
was preserved unchanged (no rewrite).

**BLOCKER fix — Field/mobile edge identity (`mobile/src/screens/Measurements.js` + new `mobile/src/measurementEdges.js`):**
Field was not sending `EdgeIn.ref`, so an ordinary Field PUT would let the backend treat an existing edge
as new (INSERT E2 + DELETE E1), defeating identity preservation. Extracted pure `edgeForEdit`/`newEdge`/
`edgeToBody` into a shared Node-testable module: existing edges now hydrate with `ref = MeasurementEdge.id`;
new edges get one stable temp key; `buildBody().edges` sends `ref = e.ref || e.id || e._k`. The ref rides
through hydrate → edit → buildBody → optimistic cache → offline queue (JSON) → PUT (verified). No Field UX,
queue, or photo behavior changed.

**Contract tests added/strengthened:**
- `mobile/src/tests/edge_identity.node.test.js` (NEW, wired into `npm run test:measurements`): existing edge
  ref survives to the queued PUT; new edge temp ref survives serialization; mixed edges keep distinct ids.
- `backend/tests/test_measurement_sketch_survival.py`: now builds a REAL connected rectangle sketch (4 graph
  edges + facet) embedding `measurement_facet_id`/`measurement_edge_id`/`measurement_penetration_id` + edge
  proposal decision; after a normal Worksheet save asserts the canonical sketch ROW is byte-for-byte
  unchanged (same id/revision_id/structure_id/document_version/document/geometry) and mappings still point to
  the surviving F1/E1/P1. Full cross-revision security matrix: foreign Structure.ref / Facet.ref / Edge.ref /
  Penetration.ref + stale UUID + foreign `structure_id`/`facet_id`/`facet_id_secondary` each → 409 (generic
  wording, no id leak), Rev A AND Rev B unmutated (savepoint atomicity).
- `backend/tests/test_measurement_sketch_clone.py`: now persists a real `MeasurementEdge`, embeds
  `measurement_edge_id`/`relational_edge_id` + `target_type:"edge"`, and asserts clone assigns a NEW edge
  UUID, remaps all edge refs to it, leaves ZERO old edge UUIDs in the cloned doc, and keeps drawing-graph
  edge ids (e1..e4) unchanged.

**Local verification (all PASS):** backend measurement/sketch/photo/takeoff regressions **38 passed** (incl.
strengthened survival + clone); node core 26 / topology 28 / edge_authority 10; office `commands` 18; mobile
`test:measurements` (incl. edge_identity 4) / `test:sketch` (sketch-cache 15 + core) / `test:sync` PASS
against the live pod backend / Expo babel-parse of Field modules OK; ruff F/E9 clean on changed tests.
**PENDING:** user Save-to-GitHub → confirm remote SHA contains all 6 files → all 5 Roof Takeoff Contract jobs
green on that SHA → STOP for independent review. (Agent cannot push / cannot read private Actions.)


## Task 4 Closure Phase 1 — Identity-Preserving Measurement Persistence (2026-06) — CODE COMPLETE & LOCALLY GREEN; CI push pending
Refactored the editable-revision save path from delete+reinsert to **identity-preserving reconciliation**
so a normal Measurement Worksheet save no longer churns child UUIDs and no longer CASCADE-wipes the
associated MeasurementSketchDocuments. Backend-only + minimal frontend edge plumbing (per user 1a-adjusted /
2a / 3a / 4b-minimal).

**Backend (`services/measurements.py`):**
- `replace_children` → new `_reconcile_children`: for structures/facets/edges/penetrations, a server-UUID
  `ref` claims an existing row owned by THIS revision → UPDATE in place (UUID kept → sketch + photos
  survive); temp/absent ref → INSERT; existing row omitted from the full PUT → DELETE (intentional; sketch
  CASCADE fires by design). Cross-links resolve against BOTH preserved and newly inserted rows.
- Ownership guard: a UUID `ref`/`structure_id`/`facet_id`/`facet_id_secondary` that belongs to another
  revision or no longer exists → **409** with a generic message (never discloses foreign data, never
  silently inserted). Non-UUID temp keys always mean NEW.
- **Summary** handled as a singleton (no ref): present+existing → UPDATE, present+none → INSERT, null →
  DELETE. `MeasurementRevisionExtension.structure_scope` rebuilt from the FINAL structure ids (deleted
  ids drop out).
- Photos: surviving children keep their UUIDs so photos are NEVER moved; only an intentionally-deleted
  child's photos are retained on the measurement revision (`_retain_deleted_child_photos`). Removed the old
  `_relink_replaced_photos` delete/reinsert relink.
- `clone_revision` now builds an old→new **edge map** and passes it to `clone_sketches`; sketch relational
  edge refs (`measurement_edge_id`/`relational_edge_id`, `target_type:"edge"`) are remapped.

**Schema:** `EdgeIn.ref` added (existing MeasurementEdge.id or temp key). No DB migration (UUID PK suffices).

**Frontend (`MeasurementWorksheet.jsx`, minimal plumbing only — NOT Phase 2 UI):** existing edges load with
`ref = MeasurementEdge.id`; new edges get a temp ref; PUT payload sends `edges[].ref = row.ref || row.id ||
row._k`. (Structures/facets/penetrations already sent refs.)

**Tests:** new `backend/tests/test_measurement_sketch_survival.py` (Postgres-backed, hermetic, flush+savepoint
isolation) proves: (1) normal save preserves every child UUID + both sketches survive + photos stay on the
same entity UUIDs (0 moved to revision); (2) omitting a structure cascade-deletes its sketch and retains its
photos on the revision; (3) mixed add/update/delete keeps survivors + sketches; (4) cross-revision ref,
stale UUID, and foreign `facet_id` fallback each → 409, and the revision is unchanged afterward.

**CI (`roof-takeoff-contract.yml`):** survival test + `services/measurements.py` / `schemas_measurements.py`
/ `routers/measurements.py` / `MeasurementWorksheet.jsx` added to BOTH path-filter blocks; the survival test
wired into the `sketch-backend-contract` pytest run.

**Local verification (all green):** sketch backend contract 38 passed (service/concurrency/clone/authz/api +
survival) incl. full measurement/takeoff/photo regressions; node core 26 / topology 28 / edge_authority 10;
frontend editor commands+history 18; Office `CI=false yarn build` succeeds; ruff F/E9 clean on changed
source. **PENDING:** user Save-to-GitHub → confirm remote commit → all 5 Roof Takeoff Contract jobs green
(agent cannot push / cannot read private Actions). STOP for independent review after that.


## Task 4 Closure Pass — PARTIAL (2026-06): CI blocker fixed; large items handed off
Branch `main`, HEAD `827f889` (== the reviewed remote main). Working tree contains verified fixes below;
Field editor / Plan 2 NOT started.

**DONE & verified this pass:**
- **Item 1 (Office CI red — root cause):** the pushed `frontend/yarn.lock` at `827f889` had NO
  `@roofspan/roof-sketch-core` entry while `package.json` requires it → `yarn install --frozen-lockfile`
  failed in `office-build`. Working-tree `yarn.lock` now includes the `file:` entry; `yarn install
  --frozen-lockfile` = PASS and `CI=false yarn build` = success locally. Needs Save-to-GitHub to land.
- **Item 18 (CI enforcement):** `office-build` job now runs `node src/components/roof-sketch/__tests__/
  commands.node.test.js` (18 assertions) before build.

**NOT YET DONE — require a dedicated session (large/interdependent, high-risk to half-ship):**
- Items 2–4: identity-preserving reconciliation for the editable MeasurementRevision whole-document
  replace (currently deletes+reinserts children → CASCADE can orphan sketches / churn mapping IDs);
  add `ref` to `EdgeIn`; sketch-survival regression tests.
- Items 5–6: async save/edit generation race + dirty-from-generation + tests.
- Items 7–9: explicit structure-safe facet mapping UI + edge mapping + edge clone remap
  (`measurement_edge_id`).
- Items 10–14: pending_accept → accepted lifecycle (only promote after authoritative measurement PUT
  succeeds+matches); discard rollback of editor-initiated worksheet changes; pending recovery on reopen.
- Items 15–17: SVG dimension labels (locked wins), real edge snapping w/ interior split, join-edge command.
- Item 19: the full new test matrix for the above.


## Plan 1 Task 4 — Office SVG Roof Sketch Editor (2026-06) — COMPLETE & locally verified
First user-visible Roof Sketch feature. Field editor (Task 6) and Plan 2 imports NOT started. Changes
staged locally on branch `main` (ahead of remote `770037d`); pending **Save to GitHub** + CI run.

**Entry point:** Property → Lead/Inspection detail → Measurements (Measurement Worksheet) → Structures →
each saved structure shows **Sketch Roof** (or **Edit Roof Sketch** if a sketch exists). Gated on a real
structure id (must Save the worksheet first). Read-only for verified/locked revisions (New Revision path
remains).

**New files (frontend/src/components/roof-sketch/):**
- `commands.js` — pure editor commands (add/move/deleteVertex, add/split/delete/setTypeEdge, create/
  delete/pitch/orientation/labelFacet, setScale, setConfirmedEdgeLength, lock/unlockEdge, place/move/
  delete/typePenetration, setProposalDecision, setEditMode). Each returns the next canonical document.
- `historyCore.js` (pure) + `history.js` (React hook) — undo/redo capped at 100, redo cleared after a new
  edit, drag commits via `pushFrom`.
- `sketchApi.js` — GET/list/PUT adapter; parses 409 (conflict+server payload), 422 (validation), locked.
- `RoofSketchCanvas.jsx` — native SVG: zoom/pan, select, connected-graph draw + closing loops, facet-from-
  edges, manual polygon, shared-vertex drag with snapping, penetration place/drag, edge-type colors,
  facet labels, validation shading. `non-scaling-stroke` keeps widths constant across zoom.
- `SketchInspector.jsx` — scale/calibrate, edge (type/confirmed/lock + discrepancy), facet (label/pitch/
  orientation), penetration controls.
- `ProposalPanel.jsx` — shared `deriveProposals`/`compareProposal`; explicit Accept Proposed / Keep Current;
  Unmapped facets cannot write to measurements (Accept disabled).
- `RoofSketchEditor.jsx` — orchestrator (full-screen modal, toolbar, history, load/init, save + dirty/
  conflict/validation states, keyboard Ctrl+Z/Y/Del/Esc, close-confirm).
- `__tests__/commands.node.test.js` — 18 pure command/state assertions.

**Modified:** `MeasurementWorksheet.jsx` (Sketch Roof button per structure; mounts editor; `applySketchProposal`
updates the in-memory worksheet draft `area_sqft`, no auto-save/verify, no takeoff recalc). `frontend/
package.json` + `yarn.lock` (`@roofspan/roof-sketch-core` file: dep). `packages/roof-sketch-core/topology.js`
+ `index.js` + `test/topology.node.test.js` (polygon-CYCLE duplicate normalization: rotation/reversal
equivalent = duplicate; same coords in a different boundary order = NOT duplicate; concave regression tests).
CI workflow path filters extended for the Office sketch files.

**Proposal safety (confirmed):** geometry only proposes; Accept Proposed is explicit and updates only the
mapped Worksheet draft fact + records `proposal_decisions`; Keep Current records rejection; locked measured
edges keep their confirmed LF (discrepancy shown, never overwritten); unscaled sketches emit NO dimensional
proposals; takeoff/estimate are never auto-recalculated.

**Verification (local, all green):** node core 26 / topology 28 / edge_authority 10; frontend editor
commands+history 18; backend sketch suite 6 passed / 0 required skips; regressions takeoff+measurement+
photos 22 passed; mobile measurements/sketch/sync green; Office `yarn build` (CI=false, as the office-build
job runs) succeeds. Testing agent: **15/15 Office UI scenarios PASSED (100%)**, no functional bugs (one
cosmetic note on initial canvas centering). Undo/redo now also flags dirty state (review nit fixed).
PENDING: Save-to-GitHub push + `Roof Takeoff Contract` Actions run (agent cannot push/read private Actions).


## Roof Sketch Foundation — Follow-up: licensing-aware API test + geometry duplicate detection (2026-06)
Two targeted fixes on top of the closure pass. Editors/Plan 2 still NOT started. Changes staged locally,
awaiting **Save to GitHub** (agent cannot push / cannot read private Actions).

- **Hermetic API test now establishes ACTIVE licensing**: `test_measurement_sketch_api.py` calls
  `licensing.service.bootstrap(db)` + `invalidate_snapshot()` before issuing requests. The app's
  `SubscriptionGuardMiddleware` (runs under httpx ASGITransport) blocks guarded `/api/measurements/...`
  routes with 403 `subscription_inactive` when the install is SUSPENDED. A fresh CI DB has no entitlement
  → previously the sketch endpoint was never reached. Dev-mode signing keys auto-generate; bootstrap
  force-refreshes an ACTIVE (`LICENSING_DEV_STATE=ACTIVE`) dev entitlement. Verified locally:
  `effective_state_cached() -> ACTIVE` (business_allowed). Idempotent (no-op when a valid row exists).
- **Duplicate-facet detection now uses CANONICAL resolved polygon geometry** (`topology.js`): keys each
  valid facet by the sorted set of its resolved boundary coordinates (edge-loop-derived for
  connected_graph, vertexIds for manual) instead of comparing raw vertex-id sets. Now catches:
  (a) identical connected edge-loop facets that have NO vertexIds, and (b) identical manual polygons built
  from DIFFERENT vertex ids at the SAME coordinates. New assertions in `topology.node.test.js`
  (now 24 assertions).
- **Local matrix**: node core 26 / topology 24 / edge_authority 10; backend sketch suite 6 passed, 0 skips.


## Roof Sketch Foundation — CLOSURE PASS (2026-06) — code complete & locally green; CI push pending
Follows the earlier hardening pass. Addresses the final GitHub-review blockers. Editors (Plan 1 Task 4/6)
and Plan 2 imports remain NOT started. Base commit `770037d` (== remote main). Changes staged locally,
awaiting **Save to GitHub** (agent cannot push; git writes go through Save-to-GitHub).

1. **CI runs on `main`**: `.github/workflows/roof-takeoff-contract.yml` push branches now include `main`
   (kept PR triggers + sketch path filters). Ensures the contract runs when sketch/measurement files land on main.
2. **connected_graph REQUIRES authoritative edgeIds**: `topology.js` — a connected facet with no/empty
   `edgeIds` is now a HARD error `facet_missing_edges` (moved out of warnings). No vertex-only fallback in
   canonical connected mode. manual_polygon still uses vertexIds.
3. **Single authoritative boundary**: new `resolveFacetBoundary(doc, facet)` in `topology.js` (exported) —
   connected derives points from the ordered edge loop, manual from vertexIds. `proposals.js` now uses it
   (was `facetPoints`→vertexIds), so a connected facet with edgeIds and no vertexIds produces a correct area
   proposal, and a facet with contradictory vertexIds is skipped (never uses the wrong boundary).
   New tests: `packages/roof-sketch-core/test/edge_authority.node.test.js` (10 assertions).
4. **Clone normalizes after remap**: `clone_sketches()` now runs the remapped document through
   `_normalize_document()` (structure/edit_mode/schema_version reconciled with the new row); fails loudly on
   an un-cloneable legacy doc. Clone test asserts row/document metadata agree.
5. **A/B PUT on the REAL route**: `test_measurement_sketch_authz.py` now calls the actual `put_sketch`
   handler (A→A/B→B allowed, cross-rep 403, owner/admin/office broad) instead of only `_scope`.
6. **Hermetic HTTP contract, 0 skips**: `test_measurement_sketch_api.py` rewritten to use httpx
   `ASGITransport` against the real FastAPI app with a `get_current_user` dependency override (generated
   principals, no live server / no password / no arbitrary property). Covers create→v1, update→v2,
   stale→409+server payload, malformed→422, locked→409, and A/B direct-UUID PUT. The old live smoke moved
   to optional `test_measurement_sketch_api_live.py` (skips without RS_TEST_* — not a CI gate).
7-11. Concurrency (2), clone remap, topology hardening, pinned field deps
   (`react-native-svg@15.12.1` + `@roofspan/roof-sketch-core` file:) and test-safety guards all preserved.

**Local verification (all green)**: node core 26 + topology 22 + edge_authority 10; mobile test:sketch (incl
sketch-cache 15) after `npm ci`; backend sketch service/concurrency(2)/clone/authz/api = 6 passed, **0 skips**
(live smoke is the only skip, in its separate optional file); regressions
takeoff/measurement/completion/lifecycle/photos/categories all pass; mobile `test:sync` green against the
pod backend URL. Single Alembic head `e0f1a2b3c4d5`. `server` imports with only DATABASE_URL (CI-safe).
**PENDING**: Save-to-GitHub push to main + actual `Roof Takeoff Contract` Actions run (agent cannot push or
read the private Actions runs).


## Roof Sketch Foundation — FINAL Hardening Pass COMPLETE & GREEN (2026-06)
Branch `agent/roof-sketch-foundation-hardening` (from remote main `7b4ddf9`). STOP condition met — the
Office/Field sketch editors (Plan 1 Task 4/6) and Plan 2 (aerial imports) are NOT started yet, per user.

- **Edge-loop topology authority (`packages/roof-sketch-core/topology.js`)**: connected_graph facets are
  validated from their ordered `edgeIds` (authoritative). Derives the vertex loop from the edge chain;
  if `vertexIds` are also present they must match the same cyclic loop (rotation/reflection) or the facet
  is rejected — two independent boundaries are never allowed. Hard errors: `broken_edge_reference`,
  `open_facet_loop`, `facet_boundary_mismatch`, `self_intersection`, `non_positive_area`, `duplicate_facet`,
  `disconnected_component` (connected mode only), `zero_length_edge`, `dangling_edge`. Warnings (recoverable):
  `possible_overlap` (interiors intersect), `possible_gap` (collinear seam without a shared edge). Manual-polygon
  mode allows independent polygons (disconnected is NOT an error there). New pure helpers exported:
  `edgeLoopVertices`, `sameCycle`, `polygonsOverlap`, `facetComponents`, `edgeMap`.
- **Overlap severity (per user)**: ordinary geometric overlap = warning; duplicate polygon / broken
  connected topology / phantom shared edge / non-positive area / self-intersection = hard error. A
  `possible_overlap` warning never hides a real topology failure (errors are computed independently).
- **Field deps**: `mobile/package.json` now pins `react-native-svg@15.12.1` and the local
  `@roofspan/roof-sketch-core` (`file:../packages/roof-sketch-core`); both resolve; `package-lock.json`
  regenerated for `npm ci` in CI.
- **Backend contracts (Postgres-backed, hermetic)** in `backend/tests/`:
  `_sketch_fixtures.py` (creates its OWN Property/User/Lead, loud teardown, wrong-DB guard, per-loop
  `engine.dispose()`); `test_measurement_sketch_service.py` (sequential CAS + normalization edge cases:
  schema_version 0/-1/"abc", empty/invalid edit_mode, malformed embedded → 422 not 500; clone + lock);
  `test_measurement_sketch_concurrency.py` (TWO real DB sessions: existing-row row-lock CAS race AND
  first-create unique-index race — the loser gets SketchConflict); `test_measurement_sketch_clone.py`
  (structure/facet/penetration/proposal target ids remapped, stable drawing-graph ids untouched);
  `test_measurement_sketch_authz.py` (two-salesperson A/B on list/GET/PUT: A→A/B→B allowed, cross-rep 403,
  owner/admin/office broad — uses fabricated principals, no real password); API test hardened with a
  same-DATABASE_URL guard + verified delete (no silent swallow).
- **CI enforcement** (`.github/workflows/roof-takeoff-contract.yml`): added branch + sketch path filters;
  fixed the stale Alembic single-head guard to `e0f1a2b3c4d5` (+ DATABASE_URL for the offline `heads` step);
  new `sketch-core` job (node `npm test`) and `sketch-backend-contract` job (postgres:16 service →
  `alembic upgrade head` → the 5 sketch pytests); mobile-contract now runs `npm run test:sketch` and
  babel-parses `sketchCache.js`.
- **Verified locally**: core 26 + topology 22 node assertions; field sketch-cache 15; backend 5 passed /
  1 skipped (API integration passes end-to-end when RS_TEST creds are supplied); full combined suite
  (sketch + takeoff + measurement) 26 passed, 1 skipped — multi-event-loop stable. NOT pushed (use Save to GitHub).


## Mobile — heartbeat + tap-to-sync chip + per-photo error detail (2026-06)
- **Keepalive heartbeat (`transport.js`):** `startTunnelHeartbeat()` (singleton, 20s) pings public `GET /api/version` through the tunnel to keep it warm and detect drops within seconds; `stopTunnelHeartbeat()` to stop. `forceReconnect()` tears down the relay socket for an immediate fresh reconnect.
- **Tap-to-sync chip (`SyncStatusChip.jsx`):** now a TouchableOpacity — tapping forces `forceReconnect()` + `runSync()` and refreshes health; shows "Syncing…" while busy; starts the heartbeat on mount. Subtext "· tap to sync".
- **Per-photo error detail (`queue.js` + `More.js`):** pending items now carry a meaningful reason — photos show "Waiting for Office — will upload when reachable" (offline) / "Office server error — will retry" (5xx); non-photos show "Waiting for Office (not reachable)" / `HTTP {s}`, with `errorCode`. Needs Attention renders `m.error` under each pending item (`att-reason-{client_id}`).
- Verified: all files babel-compile; sync lifecycle test passes; `/api/version` returns 200 unauthenticated. Needs EAS rebuild.

## Mobile — live "Connected to Office / Reconnecting…" status chip (2026-06)
- `transport.js`: module-level `_lastOkAt`/`_lastErrAt` updated on every relay response (ok), error frame, timeout, and teardown; exported `transportHealth()` → `{ online, lastOkAt, lastErrAt }` (online = a successful round-trip is more recent than the last error).
- New `components/SyncStatusChip.jsx`: polls `transportHealth()` + `lastSyncAt()` every 4s; green "Connected to Office" vs amber "Reconnecting…", with "· Last synced {relative}". testids `home-sync-chip` / `more-sync-chip` (+ `-label`, `-last`).
- Wired into `Home.js` ("My Day") and `More.js` (Sync status). Makes silent sync failures visible. Babel-compiles. Needs EAS rebuild.

## Mobile photo capture — trigger sync immediately (2026-06)
- `PhotoSection.persistAndQueue` queued the photo but never triggered a sync, so photos sat until the next trigger (and the message said "will upload when online" regardless of connectivity). Now calls `syncNow()` right after queuing (fire-and-forget) and shows an accurate "Uploading to Office now (or as soon as reachable)" message. Combined with the transport stale-socket reconnect fix, this delivers photos promptly. Babel-compiles. Needs EAS rebuild.

## Mobile sync stuck after initial connect + delete stuck items/photos (2026-06)
- **Likely root cause of "sync only works on initial connect / last_seen stops":** `RelayTransport._connect()` reused `this.ws` whenever `readyState === 1`, but a WebSocket killed by a proxy/idle-timeout keeps reporting OPEN before `onclose` fires. Requests were sent into the dead socket → 30s hang → never synced, and the socket was never torn down so every later request reused it. Fix (`transport.js`): added `_teardown()` and call it on request timeout AND send failure, so the next sync reconnects fresh (fires a new authenticated `hello`, updating last_seen).
- **Delete stuck items / photos (`More.js`, `sync.js`):** pending items (incl. photos) previously had NO remove action — only failed did. Added: per-item "Remove"/"Delete photo" button on pending items; `removeAllStuck()` (removes pending + failed) wired to a "Clear all stuck" bulk button (replaces "Remove all failed"); all with Undo. `removeMutation` already removes any state by client_id.
- Verified: all three files babel-compile; sync lifecycle node test passes. These are MOBILE changes → require an EAS/dev rebuild.
- **Still needs live diagnosis:** full sync + photo delivery + last_seen run through the live mobile→relay→Office tunnel, which can't be exercised in this preview. The transport fix is the most probable cause of the "initial-connect-only" symptom; photos also require the local-storage backend (prior fix) deployed. Ask user for relay/Office logs or the on-map error text if it persists after rebuild+deploy.

## Office — photo download + bulk geocoding backfill (2026-06)
- **Photo download:** `PhotoGallery.jsx` lightbox now has a "Download full-size" button (anchor on the auth-fetched blob URL, filename `roofspan-{category}-{id8}.jpg`). Frontend compiles clean.
- **Bulk geocoding backfill:** new `POST /api/properties/locate-unresolved?limit=N` (MANAGE_ROLES) in `routers/properties.py`. Iterates RentCast properties not yet resolved, runs `locate_property_now` (Mapbox Permanent Geocoding), skips already-resolved (saves quota). Returns categorized report: `resolved / unresolved_no_match / skipped_no_street_address / failed / skipped_already_resolved`.
- **Verified:** Mapbox geocoding token configured (len 93) and functional — "1600 Amphitheatre Parkway" → status `located`, rooftop, 37.422525/-122.0855, HTTP 200. On this pod the 156 unresolved are synthetic fixtures ("P-DNK", 2.5,2.5, no street address) → all `skipped_no_street_address` (0 real failures). Live Office has real RentCast addresses → will resolve. geojson already serves 788 placed properties.
- **Run on live:** owner/admin `POST /api/properties/locate-unresolved` once after deploy to place the real unresolved addresses. (A one-click Office admin button is a good next add.)

## Office — field photo thumbnails on property + visit history (2026-06)
- `PhotoGallery.jsx` already rendered property-level field photos (auth'd blob object URLs, lightbox with uploader/timestamp). Added a `hideWhenEmpty` prop (renders nothing while loading/empty) for quiet nested use.
- `PropertySheet.jsx`: each visit in the History list now shows a compact `PhotoGallery` (`recordType="visit"`, `hideWhenEmpty`), so roof/exterior shots taken during a specific visit appear right under that visit — in addition to the existing all-property gallery.
- Backend already supports `record_type=visit` for photo upload + list. Verified e2e on-pod: create visit → upload visit photo (201) → list returns it (count=1). Frontend compiles clean.
- Note: visually confirming the sheet requires placed property pins on the map (many are currently unresolved) — the Mapbox geocoding backfill would surface them.

## Relay device credential — one-time legacy backfill + closed fallback (2026-06)
- Added `_authorize_or_backfill_credential(db, device, credential)` in `relay/server.py`, wired into BOTH the mobile WebSocket `/mobile` `hello` (primary connection) and the tile-ticket mint (`_authenticate_relay_device`):
  - `credential_hash` present → enforce (constant-time compare) as before.
  - `credential_hash` NULL + a credential presented → ADOPT it (store sha256, commit) — one-time backfill; the device is fully enforced from then on.
  - NULL + no credential → deny (this REPLACES the prior temporary tiles-only fallback, so it's more secure).
- Effect: legacy devices quietly upgrade to a durable per-device credential on their next connect; real devices (already have `credential_hash`) are unaffected.
- Verified end-to-end on-pod (mint path): NULL→adopt (200, hash = sha256(cred)); wrong cred later → 403; correct cred → 200; NULL+empty → 403 (no adoption). Server-side only; no mobile rebuild.

## Mobile photos not syncing to Office — local filesystem storage (2026-06)
- **Root cause:** `POST /api/mobile/photos` calls `services.object_storage.put_object`, which uploaded to the **Emergent managed object-storage proxy** (`integrations.emergentagent.com`) using `EMERGENT_LLM_KEY`. On a self-hosted Windows Office that key/proxy isn't configured/reachable → `put_object` raised → endpoint returned **502** → mobile treated 5xx as transient → photos stuck **"Pending"** forever (non-photo mutations synced fine because they don't touch storage).
- **Fix (`services/object_storage.py`, server-side only):** dual backend. Uses **local filesystem** when `PHOTO_STORAGE_DIR` is set OR when `EMERGENT_LLM_KEY` is absent (self-hosted auto-fallback). Photos are written under that dir using the same relative object path stored on the `Photo` row (`roofspan/photos/{record_type}/{record_id}/{uuid}.{ext}`); `get_object` reads from there. Path-traversal components are stripped. The Emergent proxy path is preserved for the hosted/cloud preview (`EMERGENT_LLM_KEY` set + `PHOTO_STORAGE_DIR` unset).
- **Self-hosted config:** set `PHOTO_STORAGE_DIR=C:\Program Files\RoofSpan Office\Images` in the Office backend env. If unset and no cloud key, it defaults to `<backend>/data/photos`.
- **Verified end-to-end on-pod** (with `PHOTO_STORAGE_DIR` set): upload → 201, file written to the local dir with the expected folder structure, `GET /photos/{id}/content` → 200 image/jpeg, idempotency replay returns same photo (no duplicate). No mobile rebuild required — the stuck photos sync on next "Sync now" once the Office backend has this fix.

## Mobile map — ROOT CAUSE of "Imagery unavailable": legacy devices had NULL credential_hash (2026-06)
- **The real blocker:** the tile-ticket MINT (`POST /api/relay/tile-ticket`, `_authenticate_relay_device`) rejected any device whose `MobileDevice.credential_hash` was NULL with `device_auth_failed` (403) → mobile got no ticket → `satelliteUrl` null → persistent "Imagery unavailable — tap to retry". `credential_hash` is only set by `resolve_pairing`, but the column was added by a later Control-Plane migration, so **every device paired before that feature carries NULL**. The WebSocket tunnel kept working because it authenticates via the durable public-key signature, not `credential_hash` — which is why leads/area/pins loaded but satellite never did. Confirmed on-pod: all devices have `credential_hash=NULL`; mint returned `device_auth_failed`.
- **Fix (`relay/server.py` `_authenticate_relay_device`):** enforce the durable credential ONLY when `credential_hash` is present; legacy devices with NULL `credential_hash` that are still ACTIVE + paired + entitled may obtain a tile ticket (grants org-level imagery only, never user data). Verified end-to-end on-pod: mint now returns **200 + a valid ticket** for a NULL-credential ACTIVE device, and `read_ticket` decodes it.
- **Also (org-level hardening):** tile ticket no longer requires the user token — `TileTicketRequest.token` optional, `mint_ticket` uses a `-` placeholder, `read_ticket` requires only iid+did (`relay/tickets.py`). Mobile `mintTileTicket` now token-optional and returns `{ticket,status,detail}`; `MapScreen` surfaces the real failure reason ("Imagery unavailable: <detail>").
- **DEPLOY:** entirely server-side (Office backend serves `/api/relay/*`). **The user's CURRENT mobile build works once the backend is deployed — no rebuild required.** The mobile diagnostic/token-optional tweaks are optional niceties for the next build.

## Mobile map — org-level tile authorization (decouple imagery from per-user session) (2026-06)
- **User report:** on the rebuilt app the Satellite/Buildings switcher now shows (prior fix worked) but tiles fail with "Imagery unavailable — tap to retry". Root cause: the tile proxy (`/api/map/tiles/satellite`, `/api/map/tiles/buildings`) required `get_current_user`, and the relay forwarded the **individual salesperson's access token**; when it expired, org imagery broke. The MapTiler key is org-level, so tile serving must not depend on a single user.
- **Fix (server-side only — no mobile rebuild needed):**
  - `core.py`: `create_tile_token()` (short-lived, 10 min, `{"type":"tile"}`, HS256 same secret) + `require_tile_access` dependency accepting `type in {"access","tile"}`.
  - `routers/settings.py` `satellite_tile` + `routers/building_tiles.py` `buildings_tile`: now `Depends(require_tile_access)` instead of `get_current_user` (browser app still authorizes via its access token).
  - `relay/tunnel_client.py`: the Office connector swaps the forwarded token for a fresh office-signed **tile token** on `GET /api/map/tiles/*`, so tunnelled tile fetches never depend on a rep's (expiring) session. Relay can't forge tile tokens (no office JWT secret).
- **Verified (curl matrix):** tile-token & access-token → 403 (reached MapTiler w/ fake key = authorized; real key = 200 image); no-token / expired-access / refresh-token → 401; tile-token on `/api/auth/me` and `/api/mobile/leads` → 401 (type gating intact). Backend healthy.
- **Deploy note:** this is Office-backend code — the user must deploy the updated Office backend; their current rebuilt mobile app works with it unchanged.

## Mobile map — Satellite option "disappeared": robustness fix + diagnosis (2026-06)
- **Not removed:** satellite is still the 2nd basemap button; "Buildings" became a separate overlay toggle (from the prior fork's "Buildings Over Satellite" work, which was bundled into commit ae720e0). The whole `basemap-switcher` was *silently hidden* whenever `imageryReady` was false.
- **Root cause of it vanishing:** the switcher gated on `imageryReady = NATIVE_MAP_OK && maptiler_configured && satelliteUrl && buildingsUrl`. `satelliteUrl` is null until a tile ticket is minted; and `maptiler_configured` is false when the Office has no usable MapTiler key. On this pod `/api/map-config` returns `maptiler_configured:false` — the most likely reason on the user's build too.
- **Fix (`MapScreen.js`):** introduced `imageryAvailable = NATIVE_MAP_OK && cfg.maptiler_configured`; the Satellite/Buildings switcher + pin-color modes now show whenever imagery is available (never silently vanish). Tile ticket is minted **on demand** via `ensureTicket()` when Satellite/Buildings is tapped (in addition to the eager mint in `load()`), with a "Loading imagery… / tap to retry" hint overlay. Guarded the satellite raster + `mapStyle` against a null URL (no black screen). **Fixed the broken Buildings overlay** — render now keys off `overlayBuildings && buildingsUrl` instead of the impossible `activeBase === "buildings"`. `imageryReady` now only gates offline prefetch (which truly needs a ticket).
- **User action to restore Satellite:** RoofSpan Office → Settings → Integrations → MapTiler → paste + enable API key (then Settings → Maps → enable Satellite). Without a usable MapTiler key `maptiler_configured` stays false and no imagery can be shown.
- Verified: babel compiles; mapconfig/canvass/sync node tests pass. Native map needs on-device (EAS/dev build) verification — cannot render in the web harness.

## Website — Territory intelligence banner, hero map callouts, lightbox captions (2026-06)
- **Lightbox captions:** every gallery item now carries a one-line `desc`; the lightbox figcaption shows title + description (`Gallery.jsx`).
- **Hero map callouts:** subtle frosted pills ("8,029 properties", "Canvass sections") overlay the satellite AppMock, revealed with a `.callout` CSS keyframe (`Hero.jsx`, `globals.css`).
- **Territory Intelligence banner:** new full-width `TerritoryBanner.jsx` (client) — satellite map as a navy-gradient backdrop with 4 stat cards (8,029 mapped · 3,652 located · 7,529 checked · 100% coverage) that fade/rise in on scroll via IntersectionObserver (respects reduced-motion). Inserted after `BigThree` in `page.jsx`.
- Verified: `yarn build` passes; screenshots confirm hero callouts, banner stat reveal, and lightbox caption all render. Needs redeploy via Save to GitHub → Vercel.

## Website — Real RoofSpan Office map screenshots (2026-06)
- Replaced the placeholder `office-map.jpg` with three REAL Office map captures the user provided, optimized to JPEG (satellite clustered 447KB, property pins 362KB, property detail 157KB) in `public/screenshots/`.
- `Gallery.jsx` OFFICE row now shows: Satellite Territory Map, Property Pins, Property Detail (+ existing Jobs, Dashboard). `Hero.jsx` and `Sections.jsx` AppMock now use `office-map-satellite.jpg`. Old `office-map.jpg` removed (no remaining references).
- Verified: `yarn build` passes; static `out/` serves all three images (200); hero + product-tour screenshots confirm correct rendering. Needs redeploy via Save to GitHub → Vercel.

## Mobile — Silent session renewal (refresh tokens) + More page scroll fix (2026-06)
- **Root cause of "not everything syncs" (HTTP 401):** the access JWT expires after 12h (`ACCESS_TOKEN_EXPIRE_MINUTES=720`) and there was NO refresh mechanism. Once a rep's token expired, queued mutations failed with 401 while cached screens still looked fine, so the rep never realized they were silently logged out.
- **Fix — refresh tokens with rotation + reuse detection:**
  - Backend: new `refresh_tokens` table (migration `f2a3b4c5d6e7`, server-tracked jti + family). `core.py` adds `create_refresh_token`/`decode_refresh_token`/`new_token_id` (60-day default TTL, `REFRESH_TOKEN_EXPIRE_DAYS`). `auth.py`: login now returns `refresh_token`; new `POST /api/auth/refresh` (no access token required) rotates the token and detects reuse (replaying a rotated token revokes the whole family); `logout` revokes the presented family (or all of the user's tokens). `TokenResponse.refresh_token` added (optional — web ignores it).
  - Mobile: `auth.js` stores the refresh token in SecureStore (`saveTokens`/`getRefreshToken`/`clearTokens`) and exposes a module-level session-expired handler (AuthProvider clears the user → app returns to Login; offline queue preserved). Login now kicks a `syncNow`. `api.js` adds single-flight `refreshAccessToken()`; both interactive requests (`api.get`/`api.request`) and the offline queue (`send`) retry once after a silent refresh on 401. If the refresh token itself is rejected, tokens are cleared and `notifySessionExpired()` fires.
- **More page scroll:** root `View` → `ScrollView` so the full "Needs attention" list is reachable.
- Verified: backend curl covers login/refresh/rotation/reuse-detection/family-revoke/logout (all pass). New `mobile/src/tests/refresh.node.test.js` proves a queued lead stuck on 401 silently refreshes → SYNCED (no duplicate on retry) and fails cleanly with a dead session (7/7 pass). Sync lifecycle + map/canvass/pairing/transport node tests pass. All changed RN files babel-compile. Native scroll needs a dev-build glance. Not yet pushed — use Save to GitHub.


## Mobile — satellite/building tiles now load (ticket via URL) (2026-06)
- Root cause of blank satellite/building imagery on device: MapLibre-native raster/vector sources do NOT reliably send custom headers on tile requests, so the `X-RoofSpan-Tile-Ticket` header approach failed → relay returned 401 → blank (satellite showed only the bg; buildings showed no footprints while OSM/street worked because it's an unauthenticated public URL).
- Fix: `tiles.js tileTemplate(pairing, kind, ticket)` now appends the short-lived ticket as `?t=<ticket>` (the relay tile endpoint already accepts `t` as well as the header). `MapScreen.js` stores the minted ticket string and builds satellite/buildings URLs with it; `imageryReady` now requires the ticket. Header still set as a harmless secondary. Verified `?t=` auth end-to-end (returns 503 office_offline = decoded + routed, not 401).
- Combined with the prior layering fix (background-only style for satellite), satellite + building tiles should render on device like Office. Needs dev-build confirmation (live Office tunnel + MapTiler key).


- **Satellite bug fix (`MapScreen.js`):** root cause — satellite tiles rendered as a child raster ON TOP of the opaque OSM base from `mapStyle`, but child layers sit under/behind the style base, so OSM covered satellite (you saw the street map). Fix mirrors Office (which hides OSM for satellite): when `activeBase === "satellite"` the MapView now uses a background-only style (`SATELLITE_BG_STYLE`) so the satellite raster child is the visible base. Street/Buildings unchanged (OSM style + buildings overlay).
- **Undo remove (`More.js` + `sync.js`):** `removeMutation`/`removeAllFailed` now return the removed rows; new `sync.restoreMutations(list)` re-inserts them. Sync Center shows a 6s "Removed N failed upload(s) — Undo" bar (rendered outside the attention list so it persists after the list empties) for both single and bulk removes.
- Verified: files babel-compile; `photo.node.test.js` 6/6 pass. Native satellite render needs a dev-build check (MapTiler configured in Office). Not yet pushed — use Save to GitHub.


## Mobile — Sync Center bulk recovery (2026-06)
- Added "Retry all" (runs `syncNow` → revives retryable failed photos + processes pending) and "Remove all failed" (scoped bulk delete, confirmation shows the count) to the More screen's "Needs attention" section; buttons appear only when `counts.failed > 0`.
- New `storage.removeFailedMutations()` (DELETE state='failed' for active scope only) + `sync.removeAllFailed()`. Never touches pending/synced/conflict rows or other scopes.
- Verified: files babel-compile; `photo.node.test.js` 6/6 pass. Native check via dev build. Not yet pushed — use Save to GitHub.


## Mobile — Auto-retry backoff + Conflict resolver shortcut (2026-06)
- **Auto-retry backoff (`sync.js`):** while transient work remains, sync re-runs on exponential backoff (15s→30s→60s→2m→5m, capped). Retryable failed PHOTOS are quietly revived to pending each pass (capped at 6 auto-attempts) so reps rarely tap Retry. Backoff resets on reconnect, foreground, new mutation, and manual Sync. Permanent failures (`photo_file_missing`/`photo_unreadable`/`photo_unsupported_type`/413/415) are never auto-retried — classified by new pure `queue.isPermanentFailure(m)`.
- **Conflict resolver (`More.js`):** conflict items in the Sync Center now have a "Review & update" button that opens the affected record via nested navigation (`routeFor` maps lead/job/visit/inspection/photo → LeadsTab/LeadDetail, JobsTab/JobDetail, Map/Property).
- Tests: `photo.node.test.js` **6/6** (added `isPermanentFailure` classification test). All changed RN files babel-compile. Full suite: only the pre-existing unrelated `sync.node.test.js` network 404 fails. Native behavior needs a dev-build check. Not yet pushed — use Save to GitHub.


## Mobile — Replace Photo + Sync Center (2026-06)
- **Replace Photo:** failed photo items in `PhotoSection.js` now have a "Replace" action (Take photo / Library) that re-shoots without losing category/note/record — new `sync.replacePhoto(client_id, photo)` swaps the local file, keeps the SAME idempotency_key, resets to pending, and re-syncs. Refactored capture into shared `captureFrom`/`buildPhoto` helpers.
- **Sync Center:** the More screen "Needs attention" list now has per-item **Retry** and **Remove** (confirmed) on failed uploads so reps can recover any failed item in one place; removal is scoped to the single mutation (other offline work untouched).
- Verified: all touched RN files babel-compile; `photo.node.test.js` 5/5 still pass. Native interaction needs a dev-build check. Not yet pushed — use Save to GitHub.


## Mobile — photo capture crash + failed photo sync FIX (2026-06)
- **Root cause:** `queue.js makeMutation()` didn't accept/persist `photo`, so the object passed by `PhotoSection.persistAndQueue` was dropped → (1) `m.photo.uri` deref crashed the UI, (2) `api.send` `if (m.photo)` was false → photo POSTed as JSON → HTTP 422.
- **Fixes:** `queue.js` — `makeMutation` now persists `photo`; added pure helpers `isPhotoMutation/validatePhotoMeta/buildSendPlan/photoErrorLabel` + `SUPPORTED_PHOTO_TYPES`; 4xx errors enriched (errorCode + friendly message). `api.js send` uses `buildSendPlan` (photo → multipart, malformed → deterministic local_failure `photo_file_missing`, never JSON), plus lazy Expo FileSystem existence/size check. `PhotoSection.js` crash-safe render (placeholder "Photo file unavailable"/"Photo needs attention"), Retry + Remove (confirm) recovery controls, MIME/fileName from ImagePicker + local unsupported-type reject. `storage.removeMutation` (scoped single-row delete) + `sync.removeMutation`.
- Metadata survives capture→queue→SQLite→restart→retry; idempotency_key unchanged (dedup preserved). Backend `POST /api/mobile/photos` unchanged (201, multipart file/record_type/record_id, replayed dedup) — matches client.
- Tests: new `src/tests/photo.node.test.js` (5 pass) — persistence, JSON durability, send-plan, full offline lifecycle (restart→multipart→201→synced→idempotent retry, single record), malformed-legacy no-crash. Proved old makeMutation fails the regression. All RN files babel-compile. Pre-existing `sync.node.test.js` network 404 unrelated. Device/Relay/camera lifecycle needs a dev-build check (can't run here). NOT yet pushed — use Save to GitHub.


## Marketing site — differentiator & positioning upgrade (2026-06)
- Repositioned `roofspan-website` from "generic roofing CRM" to the full property→canvass→rep→lead→job→materials story. No redesign; built on existing Next.js/Tailwind/design system.
- Hero: new headline "From neighborhood to finished roof." + verified body + value-line chips ("Know the property. Assign the rep. Win the job. Order the materials. Run the roof."). Hero visual now Territory Map + Mobile My Area. Status badge/CTAs/pricing preserved.
- New sections (`Sections.jsx`): `BigThree` ("More than roofing CRM" — Property Intelligence, Territory & Canvass, ABC Supply), `MapToMaterial` (7-step lifecycle, id=how-it-works), `MobileArea` ("Give every salesperson their own area", id=sales), `AbcSupply` (dedicated, id=abc). Improved `Product` cards + 6 `Differentiators`. FAQ expanded (property/canvass/My Area/ABC/ownership) via `content.js` (also feeds FAQ schema).
- Accuracy rules honored: owner-occupied/non-owner-occupied only (no renter identity); "available info varies by source/location"; ABC Supply named (no multi-supplier claims); pricing≠availability note; offline = "locally cached + queued updates that sync"; pricing/commercial truths unchanged (config.js untouched for pricing).
- Nav (`config.js SITE_NAV`): Product / Sales & Canvassing / ABC Supply / Product Tour / Pricing / Data & Security / FAQ (anchor nav). Gallery reordered (Office: Map→Jobs→Dashboard; Field: My Area→Leads→Jobs→My Day) with updated titles/alt.
- SEO (`layout.jsx`): new title "RoofSpan — Roofing CRM, Canvassing & Operations Software", broadened description, keywords, SoftwareApplication `featureList`, FAQ schema auto-updates.
- Tests: `yarn build` static export OK; Jest **12/12**; Playwright E2E **1/1** (updated hero assertion). NOTE: not yet pushed — user must use "Save to GitHub" (agent cannot push).


## Mobile Field map — relay secret, offline prefetch, progress pins (2026-06)
- **Relay ticket secret wired:** centralized in `relay/config.py` as `TICKET_SECRET` (env `RELAY_TICKET_SECRET`); `tickets.py` now uses it so all relay nodes share one key. Added to `require_production_config()` (REQUIRED in production/multi-node). Set a stable key in `backend/.env` for local/preview. Proven: a ticket minted before a backend restart still decodes after (returns 503 office_offline, not 401) — stable across restarts/nodes.
- **Offline prefetch:** `src/offlineTiles.js` `downloadSectionArea()` builds an OSM+satellite style file and creates a MapLibre offline pack for the selected canvass section's bbox (zoom 13–18). "Download area for offline" button in the map header shows progress % / saved ✓ / retry.
- **Progress pins:** new "Occupancy | Progress" color-mode toggle. Progress mode colors pins by door-knocking status — Knocked today (green), Callback (blue), Not home (amber), Contacted (teal), Not visited (slate), Do Not Knock (red) — derived from `last_outcome`/`last_visited_at`. Legend switches with the mode.
- Tests: relay suite **25/25** (incl. cross-restart ticket stability). Mobile files babel-compile clean. Native rendering (progress pins, offline pack download/serve) needs a device dev-build check.
- Ops: for the hosted relay, set `RELAY_TICKET_SECRET` env (Fernet key) on every node; production startup now fails clearly if it's missing.


## Mobile Field map — ticket hardening, filter chips, offline cache (2026-06)
- **Tile ticket hardening (security):** replaced creds-in-URL tile auth with short-lived encrypted tickets. New `POST /api/relay/tile-ticket` (device creds + user token in BODY only) mints a Fernet-encrypted ticket (`backend/relay/tickets.py`, TTL 30m, key from `RELAY_TICKET_SECRET` or per-process). `GET /api/relay/tiles/{kind}/{z}/{x}/{y}` now reads the ticket from the `X-RoofSpan-Tile-Ticket` header, re-validates the device is still active/paired/entitled (prompt revocation), then routes with the embedded token. Tile URLs are now secret-free AND stable. Mobile: `src/tiles.js` (`mintTileTicket`, `tileTemplate`) + `MapLibre.addCustomHeader(...)` global header.
- **Filter chips:** All / Owned / Rented / Unknown chips on the mobile map header filter both pins and the list (`matchesFilter` on `owner_occupied`), mirroring Office occupancy filters.
- **Offline tile cache:** stable tile URLs let MapLibre's ambient cache serve recently viewed satellite/building tiles offline; cache raised to 120MB via `offlineManager.setMaximumAmbientCacheSize`.
- Tests: `test_relay_tiles.py` rewritten for the ticket flow — **10 pass** (mint auth 403s, mint success, unknown kind 404, missing/invalid ticket 401, offline 503, revoked-after-mint 403, full authorized route→404 w/o MapTiler, bad token→401). Full relay suite **25/25**. Mobile files babel-compile clean; native rendering still needs a dev-build check.


## Mobile Field map — Satellite/Buildings + colored pins & legend (2026-06)
- Goal: bring the RoofSpan Office map's Satellite & Buildings base views and the colored-pin legend to the RoofSpan Field (mobile) map.
- Colored pins (mobile `MapScreen.js`): data-driven `circleColor` matching Office — Owned `#16A34A`, Rented `#D97706`, Unknown `#64748B`, Do Not Knock `#DC2626` (from `theme.js` `PIN`). On-map legend overlay + colored dots in the fallback list. Uses `owner_occupied`/`do_not_knock` already present in `/api/mobile/canvass-sections/{id}/properties`.
- Base switcher (Street/Satellite/Buildings) shown only when `map-config.maptiler_configured` AND device paired + user token available. Satellite = RasterSource(512); Buildings = VectorSource `sourceLayerID:"building"` residential vs other fill/outline (mirrors Office colors).
- Satellite/Building TILE DELIVERY (chosen option a — Relay passthrough): new authed endpoint `GET /api/relay/tiles/{kind}/{z}/{x}/{y}` in `backend/relay/server.py`. Authenticates the device (installation ACTIVE + device paired + credential HMAC + entitlement, reusing the mobile-WS chain), then routes the tile request down the SAME installation tunnel to the Office's MapTiler proxy (`/api/map/tiles/...`). MapTiler key never leaves the Office. Mobile builds tile URLs via `config.js relayHttpBase()` with `iid/did/dc/tok` query params.
- Tests: `backend/tests/test_relay_tiles.py` — 6 pass (unknown kind→404, unpaired→403, bad cred→403, no tunnel→503 office_offline, full authorized passthrough routes to Office→404 w/o MapTiler, bad user token→401). Existing `test_relay.py` (15) still green. Mobile files babel-compile clean; native map rendering must be verified on a dev build (can't e2e native maps here).
- FOLLOW-UP (security hardening): tile URLs currently carry `device_credential`+user JWT as query params (HTTPS-encrypted in transit but may land in access logs). Consider short-lived signed tile tickets.


## Marketing site — real app screenshots (2026-06)
- Product tour gallery: `components/Gallery.jsx` (client) — 3 Office screens (Dashboard, Jobs, Territory Map) in browser frames + 4 Field/Mobile screens (My Day, Leads, Jobs, My Area) in a phone lineup. Click any screen → full-size LIGHTBOX (backdrop, prev/next, Esc/arrow keys, close, caption). Replaced the old static `ProductProof` block in `app/page.jsx` (ProductProof now dead code in Sections.jsx). Removed the "This website" card from DataSecurity (now 2 pieces: Office + Mobile).
- Assets in `public/screenshots/` (PIL-optimized: office pngs capped 1600w, map cropped to clean canvas as .jpg, mobile pngs capped 800w).
- Replaced the CSS-drawn `AppMock`/`PhoneMock` placeholders on `roofspan-website` with REAL captured screenshots of the running apps.
- Office (desktop, 1440x900, logged in as owner): captured Dashboard + Jobs via Playwright/Chromium against the live preview.
- Mobile (phone frame): the Expo app is native-only and crashes on web (`createPermissionHook` from expo-camera). Used a temporary `.web.js` harness (App.web.js + cache.web.js/sync.web.js shims — Metro prefers `.web` on web) to render the REAL Home/Leads/Jobs screen components with representative field data; captured, then DELETED the harness (native builds untouched).
- Assets: `roofspan-website/public/screenshots/{office-dashboard,office-jobs,mobile-home,mobile-leads}.png`. `components/ui.jsx` `AppMock`/`PhoneMock` now take `src`/`label`/`alt` props and render `<img>` inside browser/phone frames. Hero = dashboard + mobile-home; ProductProof = office-jobs + mobile-leads (copy updated: "These are real screens...").
- Build + 12/12 Jest tests green.

## Vercel deploy fix + contact email (2026-06)
- Contact email now `support@roofspan.io` everywhere (config default + `.env` + README + Jest test line 79). Site code already used `CONTACT_EMAIL`.
- Vercel 404 root cause: monorepo subdir + Next static export (`output: 'export'` → `out/`, no `routes-manifest.json`). Fix: `framework: null` (treat as static). Added root `/app/vercel.json` (builds `roofspan-website`, output `roofspan-website/out`) and `roofspan-website/vercel.json` (framework null, output `out`). Dashboard: set Framework Preset = Other, Root Directory = roofspan-website.


## RoofSpan Mobile — Salesperson App: P4–P7 DONE (2026-06)
- **P4 My Area Map:** Backend `GET /api/mobile/canvass-sections/{id}/properties` enriched with `last_outcome`, `last_visited_at`, `has_lead` (per signed-in rep) — canvass suite green. New mobile `Property.js` screen (DNK banner, owner, visit history, record-visit incl. DNK optimistic, create-lead-from-property → NewLead with preset, inspection, photos). `MapScreen.openProp` now opens Property; Map wrapped in a `MapStack` (MyArea → Property → NewLead → Inspection). No territory/RentCast/section-edit controls anywhere in mobile.
- **P5 Jobs:** Mobile `Jobs.js` (read-through cache + offline banner) and `JobDetail.js` (cache, status chips, scope/materials read-only, field-note updates, photos) drive the tested `GET/PATCH /api/mobile/jobs/{id}` with If-Match conflict + optimistic cache writes. No blank-create, no delete. Direct-UUID GET/PATCH of another rep's job = 403 (P1 tests).
- **P6 User-specific pairing:** CP migration `e1f2a3b4c5d6` adds `expected_user_id`/`expected_user_label` to `pairing_tokens` + `mobile_devices` (+index). `control_plane/service.create_pairing` binds a token to an Office user; `resolve_pairing` carries the binding onto the device and returns it; `list_devices` exposes it. CP router `/pairing/create` reads the signed body for the binding. Office `licensing/pairing_client.create_pairing(expected_user_id, label)` + new endpoints `POST /api/admin/users/{id}/mobile/pair`, `GET /api/admin/users/{id}/mobile/devices`, `POST /api/admin/mobile/devices/{id}/revoke` (SENSITIVE_ROLES). Office `Users.jsx` "Mobile" button (sales rows only) → Mobile Access dialog (Connect → numeric+token+expiry, regenerate, device list w/ status+last-seen, Revoke). Tokens are server-generated, cryptographically random, short-lived, single-use, user-bound, install-bound; QR carries no password/JWT. Tests: `test_pairing_user_binding.py` (7) + `test_pairing.py` (8) green; per-user pair verified end-to-end in preview (bound to "Sara Rep").
- **P7 My Day dashboard:** `Home.js` rebuilt — My Day stats (open leads / today's jobs / pending sync), sync status bar (label + last-sync + Sync Now + conflict/failure highlight), quick actions (New Lead / My Leads / My Area / My Jobs), assigned area card, "leads needing action" — all salesperson-scoped, no company-wide metrics.
- **Test totals (normal batched runs, all green):** backend — mobile P1/P3 25, mobile_api 11, pairing 8, pairing_user_binding 7, canvass 13-incl, assignments/photo_categories, phase3 (12) + phase4 (21). Mobile Node — scope 7, pairing 11, transport 8, live sync lifecycle. NOTE: running all network-heavy suites in one giant xdist batch causes occasional `requests` connection timeouts (shared single backend) — not regressions; they pass in normal batches/serially.
- **On-device QA still required (RN cannot run in this env):** see final report checklist (iOS+Android): QR + 6-digit pairing from Office user record, expected-user prefill at login, salesperson login, dashboard, leads CRUD + create-from-property, My Area map (MapLibre native build) + section switch + property/visit/DNK, jobs read/update, offline queue + airplane-mode + reconnect auto-sync + relay reconnect, conflict prompt, device-revoked state, cache isolation on user switch.



## RoofSpan Mobile — Salesperson Field App (P1–P3 DONE & TESTED, 2026-06)
Milestone: make Mobile a focused salesperson companion. Office PostgreSQL stays authoritative; Mobile is offline-first (SQLite cache + durable mutation queue). Decisions: Leads use soft-archive (`status='archived'`, reversible in Office, never hard-deleted); Jobs preserve the accepted-Quote→Job workflow (NO blank-create, NO delete from mobile); sequence P1→P7.

- **P1 — Security / API boundary (backend-authoritative) DONE**
  - New `services/mobile_authz.py`: `assert_lead_access`, `assert_job_access`, `property_accessible`/`assert_property_access`, `assert_inspection_access`, `assert_record_access`. Sales reach a Property only via (a) an active canvass section assigned to them, (b) a Lead assigned to them, or (c) a Job assigned to them. Management field roles keep broad access.
  - `routers/mobile.py`: full mobile Lead CRUD — `POST /api/mobile/leads` (server auto-assigns caller, ignores client `assigned_user_id`; create-from-property reuses the Property + dedupes an existing non-archived lead for that property+user; idempotent), `GET /api/mobile/leads/{id}`, `PATCH /api/mobile/leads/{id}` (If-Match 409 conflict), `DELETE /api/mobile/leads/{id}` (soft-archive). Job read/update — `GET /api/mobile/jobs/{id}`, `PATCH /api/mobile/jobs/{id}` (salesperson fields only; status transitions preserve auto-release + completion cost snapshot; no PO/costing internals exposed). `GET /api/mobile/properties/{id}` (scoped). `GET /api/mobile/inspections` + `/{id}` (scoped). Visit-create, inspection create/update, and photo upload/list/content now enforce record access for sales. Leads list excludes archived.
  - Hardened Office routers (defense in depth): `routers/leads.py` PATCH now rejects sales editing a lead not assigned to them; `routers/inspections.py` list/get/patch enforce sales scoping (no UUID enumeration).
  - Tests: `tests/test_mobile_salesperson_p1.py` (25 pass) — own-only Leads/Jobs, direct-UUID GET/PATCH/archive denials, auto-assign on create + no reassign, no blank-job-create, section/property isolation, no mobile section-edit + Office blocks sales, inspection & photo isolation, create-from-property dedupe + idempotency, If-Match conflict. Updated `tests/test_mobile_api.py` (sales visit on unauthorized property is now 403 by design). Regression: phase2/3/4 50, canvass 12, assignments, photo_categories — all green.

- **P2 — Offline data foundation (mobile client) DONE**
  - `src/scope.js` (pure): namespace cache + queue by paired installation AND user. `src/storage.js`: scoped cache keys, `pending_mutations.scope` column (additive migration), `loadPending`/`loadAllMutations` filter to active scope, `countPendingOtherScopes` (never drops other accounts' unsynced work, §29), `setInstallationScope`/`setUserScope`/`getScope`. `src/cache.js`: read-through facade (`cache.leads/lead/jobs/job/sections/sectionProperties/property/mapConfig`) → Office first, fall back to scoped cache (`stale:true`); optimistic `patchCachedList`/`patchCachedDetail`. `src/queue.js`: mutations carry `scope`. `src/sync.js`: scope-aware, single-in-flight guard, triggers on NetInfo reconnect + AppState foreground + relay-reconnect (pairingContext) + dashboard load + manual `syncNow` + on-queue; `pendingSummary` returns counts + human label + `lastSyncAt`; `onSyncChange` emitter. Scope wired in `auth.js` (login/logout) + `pairingContext.js` (installation).
  - Tests: `src/tests/scope.node.test.js` (7 pass) + existing pairing 11 / transport 8 / live-backend sync lifecycle (restart-survival, idempotent retry, conflict-preservation) all green.

- **P3 — Leads (mobile screens) DONE (backend tested; RN UI implemented, not executed here)**
  - `Leads.js` (read-through cache + offline banner + `+ New` header button + "waiting to sync" badge), `NewLead.js` (offline-queued create, optimistic list insert, accepts preset `property_id` for create-from-canvass), `LeadDetail.js` (mobile endpoints, inline Edit name/phone/email/status, field notes, visit outcomes incl. Do-Not-Knock with immediate local DNK, Archive with confirm, optimistic cache writes, offline banner), `Inspection.js` now uses scoped `/api/mobile/inspections`. `App.js` LeadStack adds NewLead + header action. Data-testids on all interactive elements.
  - Backend P3 tests added to `test_mobile_salesperson_p1.py`: lead update + If-Match conflict, mobile inspection list/detail scoping, Office inspection no-enumeration. (37 pass incl. phase3.)

- **REMAINING: P4 My Area/Map (assigned-sections UX, property statuses, offline map data, no territory/RentCast controls), P5 Jobs screens (read/update, field notes, photos, offline; no create/delete), P6 user-specific QR pairing (Office User "Mobile Access" section + single-use/expiring token + expected-user binding + revoke/re-pair; touches control_plane + relay + Office frontend), P7 salesperson Dashboard (My Day, assigned work, sync status/last-sync).**
  - NOTE: Mobile is React Native (Expo) and cannot be run/screenshotted in this environment; P2 pure cores + all backend endpoints are unit/integration-tested. RN screen UIs are validated by code review + the tested cores; on-device QA still recommended.



## Finance — Invoice View / Print / PDF / Email — DONE (2026-06)
- Finance → Invoices now has "View / Send" per invoice → `InvoiceDocumentDialog` renders a clean printable invoice (Company Profile from Settings `app_config.company_profile` + customer + property address + line items + subtotal/tax/total, records-only note).
- Backend (`routers/invoices.py`): `GET /invoices/{id}/document` (render data), `GET /invoices/{id}/pdf` (reportlab PDF via `services/invoice_pdf.py`, `%PDF` StreamingResponse), `POST /invoices/{id}/send` (emails PDF to customer via `services/email_sender.py` → Resend; sets draft→issued; logs `invoice.send`).
- Print = open server PDF and browser-print; Download PDF = blob download; Email = Resend with base64 PDF attachment + short "contact us to pay" message (RoofSpan is records-only). `tax_rate` is stored as a percent (e.g. 8.25) — displayed as-is.
- Email is a single APP-WIDE choke point (`services/email_sender.py::send_email`) — currently STUBBED (`EMAIL_PROVIDER=stub`, default): sends are logged + return a stub id, nothing is delivered; the invoice is NOT marked issued and the UI shows an honest "email delivery isn't switched on yet — use Print/PDF" message. A real transport (SMTP/Resend/SES) plugs into `_send_via_provider` behind `EMAIL_PROVIDER` later and every caller sends for free. View/Print/PDF verified E2E + tested (`tests/test_invoice_document.py`, 3 pass).


## Product
RoofSpan is a commercially distributed roofing business application:
- **RoofSpan Office**: runs locally on Windows (FastAPI backend + React browser UI + local PostgreSQL).
- **Mobile app**: React Native (Expo) companion that connects back to the local Office install via a cloud Secure Relay.
- Distribution is a deterministic Windows build pipeline: PowerShell scripts, PyInstaller (ONEDIR), WiX 5.0.2 Burn bundles, native Windows SCM services via pywin32.

## Preferred language
English.

## Architecture
- `/app/backend/`: FastAPI endpoints, Alembic migrations (`backend/alembic`, `backend/alembic.ini`, `backend/migrations_runner.py`).
- `/app/frontend/`: React browser UI.
- `/app/mobile/`: React Native Expo app.
- `/app/windows/installer/`: WiX 5.0.2 authoring (`bundle.wxs`, `RoofSpan.wxs`, PowerShell scripts).
- `/app/windows/winbuild/`: PyInstaller specs, pywin32 SCM entrypoints (`backend_entry.py`, `relay_entry.py`, `roofspan_service.py`, `db_bootstrap.py`).
- `/app/windows/tests/`: pytest regression suite (Linux-runnable static/parser guards; real MSI/exec smoke tests via GitHub Actions).
- `/app/.github/workflows/windows-build-scripts.yml`: CI proving clean Windows installs.

## Integrations
- Stripe (payments) — requires user API key.
- MapLibre GL JS / MapTiler (maps, ZIP search).
- **ABC Supply** (Desktop only) — Third-Party Aggregator OAuth 2.0 (Auth Code + PKCE). Phased build; see below and `docs/ABC_SUPPLY_INTEGRATION.md`.

## ABC Supply Integration (RoofSpan Office / Desktop only)
Goal: connect each customer's own myABCSupply account for Account/Location/Product/Pricing/Ordering/Notifications. Mobile/website/control-plane untouched. Local PostgreSQL stays authoritative; Relay is webhook transport only (Phase 4). Provider layer: `backend/integrations/abc_supply/`. Router: `backend/routers/abc_supply.py` (`/api/integrations/abc/*`). UI: `frontend/src/pages/admin/AbcSupply.jsx` (`/admin/settings/abc`). Local mock ABC server mounted at `/api/abc-mock` when `ABC_MOCK_ENABLED=true` (must be under /api/* for K8s ingress).

- **[2026-06] Phase 1 COMPLETE & TESTED** — Foundation:
  - Provider abstraction (config/auth/client/exceptions/accounts/locations/schemas), OAuth 2.0 Auth Code + PKCE (S256) connect flow, encrypted (AES-GCM) token storage + auto-refresh + rotation, reconnect_required handling.
  - Account API (search + sold/bill/ship-to + contacts; retired ship-to filtering) and Location API (search branches, get branch).
  - Settings → Integrations → ABC Supply UI: config (env/client id/secret/redirect/webhook), Connect/Reconnect/Disconnect, Test connection, Ship-To + Branch default selection.
  - DB: `abc_integrations`, `abc_account_links` (migration `a7c3f1b9d2e4`). RBAC: config/connect = owner/administrator; read = +office; sales 403. Audit actions `abc.*`.
  - Local mock ABC server (OAuth + Account + Location) for dev/test. Tests: 10 unit + 22 HTTP integration pass; in-browser OAuth round-trip validated (iteration_23). Regression (phase4 + prod_infra) green.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: real Sandbox client_id/secret + registered redirect URI; pricing/order/notification service path prefixes (`/api/pricing/v1`,`/api/order/v1`,`/api/notification/v1`) inferred, isolated in `config.py`.
  - Remaining phases: **P3** Ordering + real-time price refresh + idempotency + history/templates; **P4** Notification webhooks via Relay (ORDER_UPDATE/ORDER_INVOICED, idempotent).

- **[2026-06] Phase 2 COMPLETE & TESTED** — Product & Pricing:
  - Product API (`products.py`): `POST /api/product/v1/search/items` (contains/equals filters, embed branches, familyItems), item details, branch availability from embedded branches (Available/Not — never quantity-on-hand). Pricing API (`pricing.py`): `POST /api/pricing/v2/prices` (user token, ≤50 lines, qty/UOM/variation); $0.00 + per-line status normalized to price_status priced|unavailable.
  - PO integration: `PurchaseOrder`/`POLineItem` extended with nullable ABC metadata (migration `b2d5e7c9a1f3`); `POOut.pricing_warning`; `POST /api/purchase-orders/{id}/refresh-price` (explicit, optional apply, recomputes total, never silently overwrites manual). Changing Ship-To/branch clears gathered ABC pricing.
  - RoofSpan API: products/search, products/{item}, products/{item}/image (lazy proxy), pricing. Audit `abc.product.search/view`, `abc.price.lookup/refresh/apply`.
  - UI: `AbcProductSearch.jsx` inside `PODialog.jsx` ABC mode (Ship-To/branch context + unresolved-pricing warning). Generic POs unaffected.
  - Tests: 9 P2 unit + 14 P2 HTTP integration; **55/55 backend + full frontend flow pass** (iteration_24). RBAC (sales 403) + generic-PO regression green.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: order/notification path prefixes; product image URLs (future release per docs); recent/frequent/favorite endpoints not implemented (out of P2 need).

- **[2026-06] Phase 3 COMPLETE & TESTED** — Ordering & Order Tracking:
  - Order API (`orders.py`, `/api/order/v2`): `POST /orders` (array body; `requestId`=submission_key), `GET /orders/{n}` & `?confirmationNumber=`; order history/templates (paths NEEDS VERIFICATION, mocked).
  - Submit flow (`purchasing.py`): `abc-submit-review` (validate + MANDATORY fresh price), `abc-submit` (row-lock + re-price + block on change unless accepted + idempotent by submission_key + persist identifiers + PO→ordered), `abc-refresh-status`, `abc-reconcile`. Statuses: confirmed|price_changed|validation_failed|already_submitted|pending|failed|unknown.
  - Duplicate/concurrency: `abc_order_submissions` (submission_key UNIQUE), one confirmed per PO, `SELECT FOR UPDATE` (verified 4-way concurrent → 1 order). Unknown-state (transport/502-504) preserved, never auto-retried; reconcile via history. Receiving/inventory unchanged.
  - PO order fields + migration `c3f6a8b1d2e5`; POOut exposes them (fix in iteration_26). UI: `AbcOrderPanel.jsx` (review→price-change→submit→status/refresh/reconcile) + "ABC Supply Orders" history tab.
  - Tests: 8 P3 unit + 14 P3 HTTP integration; **all pass; frontend flow pass (iteration_26)**. RBAC + generic-PO/receiving regression green. 89 ABC backend tests total.
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: order-history & template endpoint paths/filters; notification path prefix; real Sandbox credentials.
  - Remaining: **P4** Notification webhooks via Relay (ORDER_UPDATE/ORDER_INVOICED, idempotent, pull-based status already done).

- **[2026-06] Phase 4 COMPLETE & TESTED (MOCK VERIFIED)** — Notifications & Relay Webhook Ingress:
  - Notification API (`notifications.py`, verified `/api/notification/v2/webhooks`): register/list/get/patch/delete; ONE integration webhook (client-credentials), reconciled, max-5 respected, secret AES-GCM encrypted.
  - Public ingress `POST /api/webhooks/abc/orders` (`routers/abc_webhooks.py`): constant-time secret auth (ORDER_UPDATE Authorization; ORDER_INVOICED Authorization OR apiKey — NEEDS SANDBOX VERIFICATION), strong-identifier routing, durable encrypted queue, ACK then deliver.
  - Tables (migration `d4a7b2c8e1f6`): `abc_webhook_registrations`, `abc_order_routes` (registered on Phase-3 submit), `abc_webhook_deliveries` (offline→reconnect deliver-once, bounded retry, dead_letter), `abc_notification_events` (local idempotency, out-of-order guard), `abc_invoice_events`.
  - No auto-receiving/inventory changes; local PG authoritative; central holds transport metadata only. UI: `AbcOrderPanel` push status + ABC Activity + Invoice + auto-update note.
  - Tests: 6 P4 unit + 16 P4 API; **74/74 full ABC+Relay regression, 6/6 UI checks (iteration_27), zero issues.**
  - **NEEDS ABC DOC/SANDBOX VERIFICATION**: ORDER_INVOICED secret transport; live payload/status variations; order-history & template paths; real Sandbox credentials + production webhook registration.
  - **ABC Supply integration (Phases 1–4) COMPLETE.**

- **[2026-06] Delivery Address Review & Editor COMPLETE & TESTED** — Enhancement:
  - ABC Order panel (`AbcOrderPanel.jsx`) shows a "Deliver To" review (`abc-delivery-review`) + edit modal (`abc-delivery-editor`, 9 fields). Physical delivery override defaults from the linked Job's Property/Customer via `_default_delivery()` (READ-ONLY — never mutates Job/Property/Customer), is snapshotted into `abc_order_submissions.delivery`, exposed on `POOut.abc_delivery`, and shown on submitted orders (`abc-submitted-delivery`).
  - **Delivery override is OPTIONAL** (`_validate_delivery`, purchasing.py): empty override → order falls back to the ABC Ship-To account's registered address (submit builder omits `ship_to.address`); a PARTIAL override requires the full street/city/state/ZIP set (else `validation_failed`). Ship-To account is never changed by editing the delivery destination.
  - Fixed regression where delivery was hard-required at submit (broke "ship to Ship-To default" orders and P3/P4 fixtures with no linked job).
  - Tests: new `tests/test_abc_supply_delivery_api.py` (7 pass + 1 env-only skip) + 31/31 ABC unit regression + 7/7 frontend UI flow (iteration_28). NOTE: ABC HTTP suites share an in-memory mock store — run one file at a time (serial), not under xdist.
  - Optional future polish (pre-existing, not a regression): auto-switch the open panel to the submitted view after a confirmed submit without close/reopen.

- **[2026-06] ABC Order Panel Auto-Refresh COMPLETE & TESTED** — Frontend-only UX:
  - `AbcOrderPanel.jsx` now keeps a local `poState` (synced from the `po` prop) and refetches `GET /api/purchase-orders/{id}` right after a confirmed/already_submitted submit, deriving `submitted` from it. The panel transitions to the submitted view IMMEDIATELY (confirmation #, order #, status badge, submitted timestamp, and the exact persisted `abc_order_submissions.delivery` snapshot) with no close/reopen.
  - No-override submissions show `abc-submitted-delivery-default` (ships to ABC Ship-To default); overrides show the exact snapshot (never reconstructed from Job/Property). Unknown → renders `abc-unknown` immediately (no transition); failed/validation_failed → stays in review/error; price_changed → accept → immediate submitted view. Duplicate protection/pricing/delivery validation unchanged.
  - Tests: iteration_29 — 6/6 frontend checks (all 5 submit outcomes + generic PO regression), backend snapshot verification 100%, 38+1skip ABC unit regression green. Zero issues.


## Backup Retention + Copy Health + Restore-From-Copy + ABC Go-Live — COMPLETE & TESTED (2026-06)
- **Local retention**: `local_retention` (schedule.json, default 0=keep all) prunes local backups in BACKUP_DIR to the newest N after each non-safety backup (`prune_local` — always preserves the newest `_safety` undo point; removes companion `.offsite` markers; only RoofSpan files). Saved via `PUT /api/admin/backups/schedule {local_retention}`; UI field "Keep only the newest N backups on this machine".
- **Copy health alert**: `run_scheduled_backup` + the manual copy endpoint record `offsite_last_ok_at`/`offsite_status` via `record_offsite_result`. `GET /api/admin/backups/health` now returns `offsite_enabled/offsite_last_ok_at/offsite_unreachable_days/copy_unreachable` and emits a `warn` badge ("Backup copy unreachable Nd" / "…never reached") when the copy location has been unreachable ≥3 days — surfaced automatically by the existing Dashboard `BackupHealthBadge`.
- **Restore from copy**: `GET /api/admin/backups/offsite-list` lists RoofSpan backups at the configured copy location; `POST /api/admin/backups/restore-from-copy {filename}` stages the file back into BACKUP_DIR (`stage_offsite_for_restore` — source restricted to the configured copy dir + SAFE_NAME, blocks traversal), takes a safety backup, then restores (mirrors `/backups/restore`). UI: "Restore from this location" list with per-file Restore buttons.
- **ABC Go-Live check**: `GET /api/integrations/abc/go-live-check` returns `{ready, is_mock, environment, checks[]}` — critical checks: environment==production, mock OFF, client_id+secret present, connected, required scopes granted (pricing.read/order.read/order.write/account.read); recommended: default Ship-To/branch. UI: "Go-Live check" button + checklist in Admin → ABC Supply (route `/admin/settings/abc`).
- **Tests**: `test_backup_pg_tools.py` (prune_local keep/protect-safety/zero, copy-then-prune, record_offsite_result last-ok preserved, stage_offsite validates), `test_abc_environment_switch.py` (go-live shape/env flag). 39 backup+ABC-switch tests + regressions green; frontend compiles; all UIs verified via screenshot (local-retention row, restore-from-copy list, go-live checklist).


## Windows Backup Hardening (PG discovery, ProgramData, S3 off-site) — COMPLETE & TESTED (2026-06)
- **PostgreSQL executable discovery** (`services/pg_tools.py`): `resolve_executable(pg_dump|pg_restore|psql)` finds the tool explicitly — per-tool env (`ROOFSPAN_PG_DUMP/…`), then `ROOFSPAN_PG_BIN`, then Windows `C:\Program Files\PostgreSQL\<major>\bin` (17→13 newest-first, 64/32-bit roots) + `HKLM\SOFTWARE\PostgreSQL\Installations` registry, then PATH (`shutil.which`, POSIX/dev). Never relies on Windows PATH. `services/backup.py` now invokes all three by resolved full path.
- **Clear error**: missing tools raise “PostgreSQL backup tools could not be located. RoofSpan expected PostgreSQL 16 at C:\Program Files\PostgreSQL\16\bin (could not find pg_dump.exe)…” instead of `[WinError 2]`.
- **Backup location**: `services/backup.py` default is OS-aware — Windows `%ProgramData%\RoofSpan\backups`, POSIX `/data/db/roofspan_backups`; `ROOFSPAN_BACKUP_DIR` override honored; `routers/admin_ops.py` reuses `backup_svc.BACKUP_DIR`. Installer template sets `ROOFSPAN_BACKUP_DIR=C:\ProgramData\RoofSpan\backups`.
- **Off-site (secondary) backup = local filesystem copy, no cloud** (`services/backup.py` + `offsite_backup.py`): after a successful local backup, RoofSpan optionally COPIES it to a customer-selected Windows-accessible directory (another/USB/external drive, NAS, UNC share, or a locally-synced OneDrive/Dropbox/Google Drive folder). Writes `<file>.partial` then atomic `os.replace`; original local backup untouched; `<file>.offsite` marker on success. No AWS/S3, pre-signed URLs, `EMERGENT_LLM_KEY`, `/api/offsite/authorize`, or embedded credentials. The prior S3/pre-signed client was removed. Emergent object storage was moved to `services/object_storage.py` and is used ONLY by unrelated mobile photo upload (left intact).
- **Destination config + validation**: stored machine-level in `schedule.json` (`offsite_dir`, not browser storage); `ROOFSPAN_OFFSITE_BACKUP_DIR` env default. Endpoints: `PUT /api/admin/backups/offsite-location` (save), `POST /api/admin/backups/offsite-location/test` (write/read/delete probe from the service context → friendly status, no raw tracebacks). Enabling secondary copy without a destination is rejected. Secondary-copy failure never marks the local backup failed (statuses tracked separately); destination-unavailable is handled cleanly with no crash/retry-loop.
- **Browse**: WebView2 native host-object bridge `roofspanShell.BrowseForFolder()` (in `windows/shell/Program.cs`, `FolderBrowserDialog`) opens a folder picker; the Backups page feature-detects it and always allows manual path entry. UI (`BackupStatus.jsx`) relabelled from "off-site/cloud" to "Backup copy location" with UNC guidance.
- **Security**: the copy source is restricted to RoofSpan-generated backups (`resolve_path` guards traversal); only the destination is user-controlled; no arbitrary-file copy API.
- **Copy retention (2026-06)**: `offsite_retention` (machine-level in `schedule.json`, default 0=keep all) prunes the copy location to the newest N `roofspan_*.dump` after each successful copy (`prune_offsite`; only RoofSpan files ever removed). Saved via `PUT /api/admin/backups/offsite-location {offsite_dir, retention}`; UI has a "Keep only the newest N backups at this location" field. Tested (prune keeps-newest / zero-keeps-all / non-RoofSpan-file-safe / copy-then-prune).
- **ABC Supply Production switch (2026-06)**: environment is per-install (`sandbox|production`) and switchable in Admin → ABC Supply. Switching environments now forces a clean reconnect — `PUT /api/integrations/abc/config` clears the environment-specific client_id/secret + tokens + identity and sets status `not_connected` (ABC registers separate Sandbox/Production apps). UI confirms the switch and shows a production warning. Real ABC vs mock is controlled by `ABC_MOCK_ENABLED` (unset in production installs → live ABC). Tested (`test_abc_environment_switch.py`: switch clears creds/forces reconnect, invalid env → 422, same-env save preserves client_id).
- **Windows env template** sets `ROOFSPAN_BACKUP_DIR`, `ROOFSPAN_PG_VERSION/PG_BIN`, and `ROOFSPAN_OFFSITE_BACKUP_DIR` (blank default).
- **Tests**: `tests/test_backup_pg_tools.py` (PG discovery, error msg, OS-aware dir, filesystem off-site validate/copy/atomic-partial/no-cloud-deps) + `test_backup_status`/`test_cron_backup`/`test_mobile_api` + `windows/tests` (98) — all green. Verified E2E in preview (save/test location, create backup, copy to location, file present, no `.partial`).


## ABC Supply Price Items v2 Completion — COMPLETE & TESTED (2026-06)
ABC-only pricing hardening against https://apidocs.abcsupply.com/price-items/. Preserved the existing user-token/`pricing.read`, `POST /api/pricing/v2/prices`, $0-rule, per-line status, and mandatory-fresh-order-pricing architecture; enhanced only what was incomplete.
- **Purpose**: validated to exactly `estimating|quoting|ordering` (`validate_purpose` in provider + `AbcPriceIn` field_validator → 422). Estimates→estimating, Quotes→quoting, PO/order review→ordering.
- **50-line batching**: `price_items` transparently splits >50 lines into ≤50 batches, prices each, and reconciles by stable line `id` (order preserved; a failing batch never hides good prices). `MAX_PRICE_LINES=50`. Distinct from the 99-line Place Order limit.
- **Integer quantity**: `_coerce_quantity` coerces whole floats (2.0→2) and rejects fractional/≤0 (route → 400; `_validate_and_price` → blocking error). Non-dimensional lines never send `length`.
- **Currency + requestId**: normalized line preserves `currency`/`currency_symbol`; `request_id` plumbed with meaningful ids (PO number for order flows; `-bN` per batch) and returned in results; never carries secrets/PII.
- **$0.00+OK = unavailable** (never free) and **pricing ≠ availability** preserved. Review payload now carries per-line `price_status`/`status_message`; UI shows "Unavailable" (not a $ figure) for unpriced lines and blocks submit.
- **Bulk refresh**: new `POST /api/purchase-orders/{id}/abc-refresh-all-prices` (batched ≤50, reconciled by id, explicit optional apply) + UI "Refresh ABC Pricing" button. Single-line `refresh-price` retained. Final `abc-submit-review`/`abc-submit` still force fresh `ordering` pricing + explicit price-change acceptance (no auto-accept/submit/receive).
- **Tests**: new `tests/test_abc_supply_pricing_v2.py` (19). Regression green: p2 9, p2_api 14, p3 7, p3_api 14, epic 6, delivery 7/1skip, catalog 13. Frontend testing_agent iteration_49 = 100%. Docs updated.
- **Estimate/Quote gap (documented, NOT scope-crept)**: Estimates/Quotes price from snapshotted cost + Price Books, not per-line live ABC Price Items; endpoint already accepts all purposes for future wiring.
- **Needs live Sandbox**: response field casing, dimensional variation catalog, per-account Ship-To pricing validated only against the mock (not Sandbox-certified).


## ABC Supply Order API v2 Epic (Templates, Place-Order, Get Order + History) — COMPLETE & TESTED (2026-06)
Scope strictly ABC Supply ordering; generic/non-ABC POs untouched; no ABC ordering on mobile. Preserved the v2 provider layer + mock, the reconcile fix, all P3 protections (mandatory fresh pricing, duplicate/idempotency/concurrency, unknown-state, no auto-retry, no auto-receive).
- **Reconcile 500 fixed**: `abc-reconcile` referenced non-existent `sub.created_at` (model uses `attempted_at`) + read camelCase `salesOrder`/`purchaseOrder` from a normalized (snake_case) `get_order_by_number` result. Now uses `attempted_at` + normalized `purchase_order`/`confirmation_number`/`order_number`.
- **Phase A — Templates**: `GET /integrations/abc/templates` + `/templates/{id}` (now returns `normalize_template()` shape: `lines[].item_number/description/uom/quantity/unit_price`). New `POST /api/purchase-orders/from-abc-template` (`AbcTemplateConvertIn`) creates a **normal draft** ABC PO (never submits); template prices are estimates, lines marked `abc_price_status=unavailable` so mandatory fresh pricing runs at submit. UI: `AbcTemplatesPanel.jsx` ("ABC Templates" tab — browse + pagination + detail dialog + Convert to PO → navigates to PO detail).
- **Phase B — Place Order**: `AbcSubmitIn` gained `order_comments`, `line_comments` (per `po_item_id`); `delivery` now carries `requested_date`, `appointment_time`, `contact_email`. Order builder sends `comments`, per-line `comments`, `dates.deliveryRequestedFor`/`deliveryAppointmentTime`. Validation in `_validate_and_price`: `MAX_ORDER_LINES=99`, `PO_FIELD_MAX=20` (no more silent PO-number truncation), dimensional length required. UI: `AbcOrderPanel.jsx` options block (delivery service selector OTG/OTB/WCL, requested date, appointment, order comments, per-line comments) + deeper submitted-view financials/branch/dates.
- **Phase C — Get Order + History**: `GET /integrations/abc/orders/history` returns `{pagination, items}` with each item enriched `roofspan_matched/roofspan_po_id/roofspan_po_number` (strong-match by `external_order_number`; never assumes ABC-origin). `GET /integrations/abc/orders/{id}` attaches the same RoofSpan match. UI: `AbcOrderHistory.jsx` ("ABC Supply Orders" tab — date filters + pagination + PO-link/"Placed directly with ABC" + order detail dialog with amounts/branch/shipments/lines). `PurchaseOrderDetail.jsx` now opens `AbcOrderPanel` directly for ABC POs (incl. jobless template-converted POs) — fixes the convert→submit journey.
- **Tests**: new `tests/test_abc_supply_epic.py` (6: template convert draft-not-submitted, converted-PO requires fresh pricing, 99-line block, comments+appointment submit, history+detail RoofSpan matching). Stale `test_abc_supply_p3.py` history/template unit tests updated to v2 shapes. Green: p3 unit 7, p3 api 14, epic 6, delivery 7+1skip, phase3 14, phase5 7, catalog 13. Frontend testing_agent iteration_48 = 100% (all new UI flows; one UX gap found — jobless converted PO couldn't open the ABC panel from PO detail — FIXED). NOTE: ABC HTTP suites share an in-memory mock store — run one file at a time; history-matching tests use `items_per_page=200` to be store-size robust.
- **Docs**: `docs/ABC_SUPPLY_INTEGRATION.md` updated to the verified v2 endpoints (`/orders/orderHistory`, `/orders/templates`), template-convert flow, place-order fields, history matching; removed obsolete "order-history/template paths inferred/NEEDS VERIFICATION" notes.



## Cloud deploy (Railway)
- **roofspan-website** (marketing site): service Root Directory `/roofspan-website`, Nixpacks. Config at `roofspan-website/railway.json` (build `yarn build`, start `yarn serve`). Config-as-code path in Railway must be `/roofspan-website/railway.json` (absolute from repo root — it does NOT follow Root Directory).
- **Control Plane** (`cp.roofspan.io`, serves `backend/cp_asgi.py:app`): Dockerfile build via root `railway.json` → `deploy/railway/Dockerfile`. **Build context = repo root** (Dockerfile `COPY backend/ /app/`), so the Railway service Root Directory MUST be empty/repo-root. Required env vars documented in `deploy/railway/README.md` (CONTROL_PLANE_DATABASE_URL, Stripe, KMS, operator issuer/audience) — startup fails-closed without them.
  - **[2026-06] Recovered lost deploy files**: a Save-to-GitHub conflict merge (PR#2 `conflict_190826_0821`) left `main` without `deploy/railway/*`, root `railway.json`, and `backend/cp_asgi.py`; the Railway build then failed with `COPY backend/ → "/backend": not found`. Restored all 4 files from PR#2 onto current `main`; verified `cp_asgi:app` imports and exposes `/health`.
  - **[2026-06] Fixed CP startup crash `ModuleNotFoundError: psycopg2`**: Railway's `DATABASE_URL` is a plain `postgresql://…`, which made `create_async_engine` pick the sync psycopg2 dialect. Added `_to_async_url()` in `backend/control_plane/config.py` to normalize any `postgres://`/`postgresql://`/`+psycopg2`/`+psycopg` URL to the canonical `postgresql+asyncpg://` (the CP sync paths already convert away from `+asyncpg` to psycopg v3). Verified `cp_asgi` imports with a Railway-style URL.
  - **Healthcheck note**: `/health` returns 200 regardless of DB, but the startup event runs first. `require_production_config()` only enforces when `CP_ENV=production` and then requires: `BILLING_MODE=stripe`+`STRIPE_SECRET_KEY`+`STRIPE_WEBHOOK_SECRET`, `CP_KMS_SIGNING_KEY_ID` (if `ENTITLEMENT_SIGNER=kms`), and `CP_OPERATOR_ISSUER`+`CP_OPERATOR_AUDIENCE`. `init_control_plane()` also needs the DB reachable (bounded retry). For a first smoke test, leave `CP_ENV` unset so only the DB is required.

## Inventory Core 2.0 (multi-slice, in progress 2026-06)
### Slice 1 — Data model foundation + SupplierMaterial + ABC backfill (COMPLETE & TESTED)
- Master fields added to `materials` (manufacturer, brand, product_family, subcategory, color, size_variant, purchase_unit, conversion_factor, coverage_amount/unit, weight, upc, manufacturer_part_number, taxable, image_url). Legacy `abc_*` columns retained for backward compat.
- New `supplier_materials` (generic supplier↔material mapping, source of truth; `is_preferred` = user-selected primary, at most one active per material). `suppliers.integration_provider` added.
- Migration `a1b2c3d4e5f6` (down_revision f1a9c4b7d3e2): additive + backfill — seeds "ABC Supply" supplier and a preferred ABC SupplierMaterial for every existing abc-linked material.
- ABC add-to-inventory now also creates/links a SupplierMaterial (new + dedupe paths). New service `services/inventory_core.py` (ensure_supplier, upsert_supplier_material, set_preferred_supplier, compute_quantities, best_known_cost, preferred_supplier_material — quantities/preferred used in later slices).
- API: `GET /api/materials/{id}/suppliers`. Tests: `tests/test_inventory_core_slice1.py` (4 pass). Regression: ABC unit 31, catalog 13, api_integration 23, p2/p3/p4_api 44, delivery 7/1skip, phase5 subset — all green.
- Remaining slices: 2) quantities+ledger types, 3) Materials list revamp+filters, 4) Material Detail page, 5) Add Material (Search/Custom/CSV)+adjustment dropdown, 6) preferred-supplier mgmt+Best Known Cost+full regression.

## Supplier Framework (Part B) — IN PROGRESS (2026-06)
- **Slice 2 backend (Supplier model + CRUD/detail) DONE & TESTED**: Supplier expanded (supplier_type, account_number, sales_rep, ordering_email, website, payment_terms, default_branch, delivery_terms, minimum_order, freight_notes, tax_notes, integration_status, updated_at). APIs: `GET/POST /suppliers` (search/active filter), `GET /suppliers/{id}` (detail+products), `PATCH /suppliers/{id}`, `POST /suppliers/{id}/active?active=`. Secrets never exposed.
- **Slice 3 (Generic connector + ABC adapter) DONE**: `integrations/supplier_connectors.py` — `SupplierConnector` w/ Capability enum, `AbcSupplyConnector` (wraps existing ABC, declares catalog_search/live_pricing/branch_availability/online_order_submission/order_status/order_cancel/account_discovery), `ManualSupplierConnector` (no live caps). Capabilities surfaced on SupplierOut + facets. ABC code unchanged (all ABC tests green).
- **Slice 6 (Manual supplier products + price history) DONE & TESTED**: `POST/PATCH /supplier-materials` (manual mappings: item#, desc, uom, conversion, mfr part#, cost, lead time, notes). Immutable `supplier_price_history` snapshots on every manual cost change. `GET /supplier-materials/{id}/price-history`. Dedup now keys on supplier_id (fixed cross-supplier reuse). Best Known Cost = lowest active cost, shown separately; Preferred never changes from price. Audit on supplier + supplier_material + price changes.
- Migration `d4e5f6a7b8c9` (down c3d4e5f6a7b8): additive suppliers columns + supplier_price_history; backfill integration_status='manual' for non-ABC, supplier_type for ABC. Applied cleanly.
- Tests: `tests/test_supplier_framework.py` (3 pass). Regression green: inventory 13, hardening 6, ABC unit 31, catalog 13, api_integration 23.
- **REMAINING**: Slice 2 frontend (Supplier management UI + detail), Slice 4 (remove PO "ABC Supply" name-magic → Supplier-record select driving connector), Slice 5 (Universal Product Catalog UI + supplier comparison + price-freshness labels), Slice 7 (full frontend regression + UX polish).

### Part B FRONTEND (Slices 2,4,5,7) — COMPLETE & TESTED (2026-06)
- **Slice 2 Supplier Management UI**: `frontend/src/pages/Suppliers.jsx` wired to top-level `/suppliers` route + new sidebar nav item (`nav-suppliers`, between Inventory & Finance). List (search, active/inactive filter), Add/Edit manual supplier, Deactivate/Reactivate. Detail dialog shows full Overview (type/account/contact/rep/phone/email/ordering email/website/terms/branch/delivery/min order/freight+tax notes/capabilities/notes), Products (material, item#, UOM, cost, price-freshness badge, preferred star), and Recent Purchase Orders. Backend `GET /suppliers/{id}` now returns `purchase_orders` + enriched products (supplier_uom, price_status, price_updated_at).
- **Slice 4 PO Supplier Selection Refactor**: `PODialog.jsx` free-text supplier replaced with a Supplier **dropdown** loaded from `/api/suppliers`. ABC behavior now driven by `supplier.integration_provider === 'abc_supply'` (NO name-magic). `POIn` gained `supplier_id`; `create_po` resolves by `supplier_id` first (persists real supplier identity), falls back to `supplier_name` for legacy compat. Manual suppliers → standard material-line flow; ABC → Ship-To/Branch + live product search. Supports `initialSupplierId`/`initialMaterialId` presets for catalog "Add to PO".
- **Slice 5 Universal Product Catalog**: `AbcCatalog.jsx` transformed into `ProductCatalog.jsx` at `/inventory/catalog` (title "Product Catalog"); `/inventory/abc-catalog` now redirects there. Source selector: "All sources (RoofSpan)" + each supplier. All-sources shows master materials comparison table (Preferred Supplier vs Best Known Cost, distinct; price-freshness badges Live/Cached/Manual/Stale/Unavailable + timestamp — no invented stale threshold). ABC source preserves full ABC experience (sync, ship-to/branch context, availability, live pricing, dimensional handling, add-to-inventory). Actions: Add to Inventory, View Material, Add to PO (no estimate/quote/job actions). Backend `GET /materials` enriched with `primary_supplier_provider/status/updated_at`, `best_supplier_name/provider/status/updated_at`, `supplier_count` (new `inventory_core.best_known_supplier_material` + `supplier_material_count`).
- **Slice 7 UX/Regression**: obsolete "Type ABC Supply" copy removed; Inventory catalog button relabeled "Product Catalog". Backend regression green: supplier_framework+inventory core+hardening 22, ABC catalog 13 (serial), phase5+p1+p3_api 31. Frontend testing_agent iteration_34 = 100% (29/29 checks, zero bugs). No name-based ABC behavior remains in PO creation. ABC is now one supplier/source inside the Product Catalog.

## Inventory Core 2.0 — Hardening (Part A) COMPLETE & TESTED (2026-06)
- **CSV parser** moved server-side to Python's standards-compliant `csv` module (`routers/operations.py::_parse_csv_text`): quoted fields, commas inside quotes, escaped `""`, CRLF/LF, UTF-8 BOM, blank optional fields, header validation (needs sku or name). `/materials/import/preview` + `/commit` now accept `csv_text` (rows still supported). Preview/confirm workflow unchanged. Frontend sends raw file text.
- **DB preferred-supplier invariant**: migration `c3d4e5f6a7b8` resolves any existing duplicates non-destructively (keep earliest created preferred, unset rest, RAISE NOTICE count) then creates PARTIAL UNIQUE INDEX `uq_supplier_materials_one_active_preferred ON supplier_materials(material_id) WHERE is_preferred AND active`. Service `set_preferred_supplier` reordered (clear others → flush → set chosen) so the index is never transiently violated.
- Tests: `tests/test_inventory_core_hardening.py` (6 pass — CSV quoted/escaped/CRLF/header-validation + DB rejects 2nd active preferred via savepoint). Regression green: inventory 13, ABC unit 31, catalog 13, api_integration 23.
- **Part B (Supplier Framework & Universal Product Catalog) — NOT STARTED** (7 slices: Supplier model+UI, connector abstraction+ABC adapter, remove supplier-name magic in PO, Universal Product Catalog+comparison, manual supplier products+price history, preferred workflow, regression).

### Slices 2–6 — COMPLETE & TESTED (2026-06)
- Slice 2 Quantities & Ledger: `services/inventory_core.compute_quantities` (On Hand/Reserved/Available=OnHand−Reserved/On Order=Σmax(qty−received,0) on open POs/Required=active-job plans/Projected=OnHand+OnOrder−Required). Structured TXN_TYPES; `job_reservation` never reduces On Hand. Migration `b2c3d4e5f6a7` adds inventory_txns.job_id+location. Endpoint `GET /materials/{id}/quantities`.
- Slice 3 Materials List 2.0: `GET /materials` returns quantities + preferred supplier + best_known_cost + status, with filters q/category/manufacturer/supplier_id/active/low_stock; `GET /materials/facets`. Frontend Inventory materials tab revamped (new columns + filter bar + row→detail).
- Slice 4 Material Detail: `GET /materials/{id}/detail` (overview, quantities, suppliers, open POs, jobs, txn history). Frontend `MaterialDetail.jsx` at /inventory/materials/:id.
- Slice 5 Add Material/CSV: 3-mode add (Create custom / Search supplier catalog / Import CSV). `POST /materials/import/preview` + `/commit` (create + update-by-SKU, preview of actions, confirm_updates required + UI checkbox — no silent overwrite).
- Slice 6 Adjustment+Preferred: adjust reason is a structured dropdown + notes (validated ∈ TXN_TYPES). `POST /materials/{id}/suppliers/{sm_id}/prefer` (exactly one active preferred/material). Best Known Cost shown separately from preferred supplier.
- Tests: `test_inventory_core_slice1.py` (4), `test_inventory_core_slice2_6.py` (9, incl. exact quantity math + reservation invariant + CSV confirm). Frontend testing_agent iteration_33 = 100% (10/10). Full ABC + business-workflow regression green.

## ABC branch selection fix (2026-06)
- **Bug (live sandbox):** after connecting real ABC and choosing a Default Ship-To (Big Pine 2010466-2), the Default Branch dropdown was empty → couldn't save a branch → ABC Catalog blocked with "Select a Branch".
- **Root cause:** `GET /branches?ship_to=` re-fetched the Ship-To DETAIL endpoint, whose response omits the branch list for some accounts (even though the account SEARCH result that populated the picker had branches).
- **Fix:** `list_branches(ship_to)` now sources branches from the account SEARCH result first (`list_ship_to_accounts` match), then falls back to Ship-To detail, then to a Location API branch search by the ship-to's state. Frontend `AbcSupply.jsx` also seeds the branch dropdown from the selected account's embedded branches while the API resolves. Mock models the real case via Ship-To `2010466-2` (search has branches; detail omits them).
- **Tests:** new `test_06b_branches_when_shipto_detail_omits_branches` + updated accounts-filter test; full ABC regression green; frontend verified 100% (iteration_32).

## ABC Supply Vendor Catalog (Inventory) — COMPLETE & TESTED (2026-06)
- **Goal:** browse/search the ABC catalog inside Inventory, see branch availability + customer pricing, and "Add to Inventory" to create a RoofSpan Material that preserves the ABC item identity for future ordering. Catalog = VENDOR data, kept separate from RoofSpan on-hand stock; branch availability is never treated as quantity-on-hand.
- **DB:** new `abc_catalog_items` (vendor cache, unique `abc_item_number`, `material_id` link, `raw_data`, `status` active/inactive, `branch_numbers`), `abc_catalog_sync` (singleton sync status). Material gained nullable `vendor`, `abc_item_number` (indexed), `abc_catalog_item_id`, `abc_uom`, `abc_metadata`. Migration `f1a9c4b7d3e2` (down_revision d4a7b2c8e1f6), additive-only.
- **API (all /api/integrations/abc, RBAC owner|administrator|office):** `GET /catalog` (q,page,page_size,category,active_only,branch,live — serves local cache, warms/queries ABC live when empty/requested), `GET /catalog/{item_number}`, `POST /catalog/{item_number}/add-to-inventory` (create OR dedupe by abc_item_number; on-hand defaults 0; never duplicates identity), `POST /catalog/sync[?full]` (background full/incremental via `sinceLastModifiedDateTime`; upsert; inactive→marked inactive, never deleted), `GET /catalog/sync/status`. Pricing reuses `POST /pricing` (batch, visible page). ABC APIs: POST /product/v1/search/items (live search), GET /product/v1/items (full sync), POST /pricing/v2/prices; availability derived from embedded branches (ABC exposes no stock qty).
- **UI:** `/inventory/abc-catalog` (`AbcCatalog.jsx`) — Ship-To/Branch context, Sync button+status, search (description or item#), paginated results with availability badges (Available/Not at branch/Unknown — never a number), batch customer pricing, Add to Inventory / In Inventory. Entry button on Inventory Materials tab. Disconnected/needs-selection banners route to Settings → ABC Supply.
- **Tests:** new `tests/test_abc_supply_catalog_api.py` (13 pass: mapping, sync, active/inactive, search by desc+item#, pagination, add+dedupe, ABC identity preserved, on-hand=0, no token leak, sales 403). Full ABC regression green (31 unit + 22 + 14 + 14 + 16 + 7/1skip). phase4/phase5 (materials/PO/receiving) 21 pass. Frontend UI 100% (iteration_31). No real ABC credentials committed (only synthetic mock values in tests).

## Live ABC Sandbox — OAuth redirect URI (2026-06)
- **User hit ABC/Okta HTTP 400 on Connect** ("'redirect_uri' must be a Login redirect URI in the client app settings") when using their REAL ABC sandbox credentials from their local Windows install. **Root cause: external ABC Developer Portal config**, NOT a RoofSpan bug — the redirect URI `http://127.0.0.1:8001/api/integrations/abc/callback` was not registered byte-for-byte in the ABC app's "OAuth 2.0 Redirect URI(s)". RoofSpan already sends the configured URI correctly (PKCE S256, Basic-auth token exchange) — confirmed via integration_expert.
- **Fix = user action:** register that exact URI (scheme `http`, host `127.0.0.1` not `localhost`, port 8001, path, no trailing slash) in the ABC portal, then retry. If 400 persists after saving, wait/retry or have ABC Support confirm portal→Okta propagation.
- **In-app aid added** (`frontend/src/pages/admin/AbcSupply.jsx`): prominent amber callout (shown when not connected & not mock) with the exact effective redirect URI + Copy button, plus an always-visible Copy affordance on the OAuth Redirect URI config field. Verified iteration_30 (100%, mock-mode gating correct, no regressions).

## Completed (this session)
- **[2026-06] Reconciled 3 stale pytest failures after upstream git pull (110 commits → aab2d95).** All were stale test assertions from legitimate upstream refactors; production behavior intact:
  - `test_spec_datas_reference_real_backend_alembic`: broadened `"migrations" not in spec` → now forbids only the removed `backend/migrations` dir, allows the `migrations_runner` hiddenimport.
  - `test_released_orphaned_revision_is_explicitly_reconciled`: split the contiguous sentinel-string assertion into two fragments (message is now spread across two string literals).
  - `test_backend_surfaces_and_logs_lifespan_startup_failure`: inject a no-op `migrations_runner` module so the test focuses on the uvicorn started=False lifespan path without a real DB call.
  - Result: **97 passed, 4 skipped, 0 failed.**
- Prior: WiX5 bootstrapper ext name; Burn PostgreSQL/PgSuperPassword wiring; SCM virtual-account names; native pywin32 SCM services; first-install DB/role bootstrap via DPAPI; ONEDIR payload validation; Burn duplicate CacheId; uvicorn no-console isatty fix; lifespan startup failure reporting.

## Backlog
- **P1 — Sign & Publish**: wire Authenticode signing + CloudFront release upload into Windows build/release scripts.
- **P2 — Core app workflows**: job/project workflows, field workflows, photos, measurements.

## Testing notes
- Windows build path is tested on Linux via pytest static/parser guards. Real MSI + execution smoke tests run only via GitHub Actions. Do NOT claim a build/installer fix "verified" unless CI or the corresponding suite confirms it.
- Credentials: `/app/memory/test_credentials.md`.

## Git workflow
User develops on remote `Asgard-Solutions/roofspan` and periodically asks to `git fetch` + `git merge --ff-only`. Cannot push back directly — use "Save to GitHub". Preserve `.git`/`.emergent`.

## Estimating Modernization — COMPLETE & TESTED (2026-06)
Goal flow: Supplier Cost → RoofSpan Material → Estimate → Waste/UOM/Assemblies → Markup/Margin → Customer Quote. Customer selling price is NEVER the same as supplier cost; historical estimates/quotes retain pricing snapshots.
- **Architecture**: `Material → SupplierMaterial → Supplier → SupplierConnector`; `Estimate → EstimateLineItem (catalog-linked, cost/waste/markup/snapshot/assembly fields)`; `Assembly → AssemblyItem`; `PriceBook → PriceBookEntry`; `Quote → QuoteLineItem (+ package_id)` and `Quote → QuotePackage` (Good/Better/Best).
- **Migration `e5f6a7b8c9d0`** (down `d4e5f6a7b8c9`): additive-only. Extends `estimate_line_items` (material_id, supplier_material_id, line_kind, base/material/labor/equipment/subcontract cost, measured_quantity, waste_percent, order_quantity, purchase_unit, conversion_factor, markup_percent, selling_unit_price, cost snapshot provenance, assembly snapshot); backfills selling_unit_price=unit_price & measured_quantity=quantity. New tables: `assemblies`, `assembly_items`, `price_books` (+partial-unique one-default index), `price_book_entries`, `quote_packages`; `quotes` gains multi_package + accepted_package_id; `quote_line_items` gains package_id + internal cost snapshot. Seeds one neutral default 'Standard' price book.
- **Calc engine** `services/estimating.py` (server-authoritative): calculated_quantity=measured*(1+waste/100) (measured NEVER overwritten); markup%=(price-cost)/cost*100 vs margin%=(price-cost)/price*100 (distinct); order_quantity=ceil(calc_qty*conversion_factor) (explicit, never guessed; validation-safe None when no conversion); summarize() → material/labor/equipment/subcontract/estimated_total_cost, selling, gross_profit, gross_margin%.
- **APIs**: estimates `GET/POST/PUT` now snapshot cost + compute lines + RBAC-gated `cost_summary`/`can_see_cost` (owner/admin/office only; sales sees selling price only); `GET /estimates/{id}/cost-refresh/preview` + `POST .../apply` (explicit, never auto-applies, optional sell recalc). `POST /quotes` snapshots SELLING prices (+internal cost hidden from output) and supports `multi_package`+`packages`; `POST /quotes/{id}/accept` records `accepted_package_id`. New router `/api/estimating`: assemblies CRUD + `/expand` (snapshots version+cost), price-books CRUD + `/entries`, one-active-default enforcement.
- **UI**: dedicated `/estimates/:id` Estimate Editor (Add Item → Search Product Catalog / Add Assembly / Add Custom Line; measured/waste/qty, cost/markup/sell with two-way calc, cost/margin summary gated, Cost Refresh dialog, Generate Quote). New top-level 'Estimating' sidebar (owner/admin/office): Assemblies + Price Books management pages. LeadDetail: New estimate → editor; multi-package quote display + package-selecting acceptance.
- **Tests**: `tests/test_estimating_modernization.py` 12 pass (calc math incl 31.5+12%→35.28, markup≠margin, ceil order qty, waste summary, default price book, assembly expand+version bump, quote cost-hidden snapshot, multi-package accept, cost-refresh no-autoapply, legacy custom line). Regression: phase3 14, phase5 7, supplier framework 3, inventory core 13+6 — all green (hardening's DB-invariant test must run in isolation due to a cross-file async event-loop teardown artifact). Frontend testing_agent iteration_35 = 100% (13/13 features), zero bugs.
- **Known limitations**: Price Book rules are managed but NOT yet auto-applied to editor lines (adding a catalog product defaults selling_unit_price=snapshot cost until markup/price set) — candidate next enhancement. Job Material Automation / Smart Purchasing NOT started (deferred per instruction).

## Advanced Inventory Completion Pass — DONE & TESTED (2026-06)
Finished deferred operational UI + the ABC integration gap; fixed an integrity gap.
- **Cycle Count UI**: guided count inside Location detail (`start-cycle-count` → editable counts + live variance → posts via `/inventory/cycle-count`, server-authoritative, refreshes balances).
- **Stock By Location** on Material Detail (`detail-by-location`): per-location on-hand + Total that equals company On Hand; existing On Hand/Reserved/Available/On Order/Required/Projected retained.
- **Inventory Transactions** page `/inventory/transactions` (filters material/location/type; clickable job/PO links) — over existing `/inventory/transactions`.
- **ABC PO from job shortage & Reorder**: proposal/reorder now pass `integration_provider="abc_supply"` + per-line ABC metadata when the chosen supplier is ABC (capability-driven, no name-matching). Resulting PO is `integration_provider=abc_supply`, stays draft (never auto-submitted); PO detail shows "Review & submit in ABC" entry to the existing ABC panel. Verified by test `test_abc_provider_po_recognized_and_draft`.
- **Integrity fix**: materials created/imported/manually-adjusted now keep `Σ(InventoryBalance) == Material.quantity_on_hand` via `inventory_ops.sync_default_balance` (called from material create, CSV import, and on-hand adjust). One-time reconcile healed 84 existing materials.
- **Tests**: Advanced Inventory 11 (incl. ABC-draft-recognition + transaction-history-capture), Inventory Core slice1 4 + hardening 6, Estimating/Supplier/Core 24 — all pass. Frontend testing_agent iteration_38 = 100% of the 6 new UI surfaces, zero UI bugs.
- **Still DEFERRED (transparent)**: PO status-history timeline table (Slice 4) and receiving photo attachments (Slice 5) were NOT implemented this pass (chose not to add the additive status-history model / attachment wiring under budget). Actual Job Costing NOT started.

## Git workflow (legacy note)
User develops on remote `Asgard-Solutions/roofspan`; use "Save to GitHub". Preserve `.git`/`.emergent`.

## Advanced Inventory Operations — CORE COMPLETE & TESTED (2026-06)
Physical lifecycle: Purchased → Received (to location) → Stored → Reserved → Issued → Consumed → Returned/Waste → Job closed.
- **Architecture**: Material → InventoryBalance → InventoryLocation → InventoryTxn (location-aware) → JobMaterial → PurchaseOrder. `Material.quantity_on_hand` is kept == Σ InventoryBalance (so Inventory Core stays intact); reservations remain location-agnostic ledger entries.
- **Migration `a7b8c9d0e1f2`** (down `f6a7b8c9d0e1`): additive — tables `inventory_locations`, `inventory_balances`; `inventory_txns` + source/destination_location_id. Seeds default 'Main Warehouse' and backfills every material's quantity_on_hand into a balance there (totals preserved).
- **Quantity rules**: On Hand = Σ balances; Available = On Hand − Reserved; reservations NEVER change On Hand; transfer nets to zero; receive/return +On Hand once; issue/waste/damage/loss −On Hand once; issue consumes reservation first; Net Used = Issued − Returned (Waste shown separately); auto-release of remaining reservations on job completed/cancelled (idempotent, no On Hand change).
- **APIs (services/inventory_ops.py, routers/inventory_ops.py `/api/inventory`)**: locations CRUD + `/locations/{id}` detail, `/balances?material_id=`, `/transfer`, `/issue`, `/return`, `/disposition` (waste/damage/loss), `/cycle-count`, `/transactions` (filters: material/location/job/po/reason). PO receive gained `location_id`. Jobs PATCH auto-releases on completed/cancelled. material-plan rows now include issued/returned/waste/net_used.
- **UI**: `/inventory/locations` (Inventory Locations page: CRUD, detail w/ balances + recent txns, Transfer dialog). Job Material Plan: Issue/Return/Waste actions + Issued & Net Used columns. PO detail Receive dialog: receive-to-location selector. Inventory toolbar: Locations button.
- **RBAC/Audit**: all mutations gated to owner/admin/office; location/transfer/issue/return/waste/loss/cycle-count/auto-release audited.
- **Tests**: `tests/test_advanced_inventory.py` 9 pass (backfill==on_hand, transfer net-zero, same/insufficient rejected, issue-consumes-reservation & reduces on_hand once, return restores, waste reduces, cycle-count adjustment, auto-release idempotent). Job automation 6, phase5 7 pass. Frontend testing_agent iteration_37 = 100% backend & frontend, zero bugs.
- **Backend-complete but UI DEFERRED (next)**: Cycle-count UI (API+tests done), Material Detail by-location breakdown (GET /balances done), Inventory Transactions history page (GET /transactions done), PO status-history timeline table (Slice 18), receiving photo attachments (Slice 17), and ABC job-shortage→ABC-submit continuation (Slice 19 — proposal currently creates manual draft POs; ABC electronic submit remains via the existing ABC order panel). Actual Job Costing NOT started (deferred).

## Job Material Automation & Smart Purchasing — COMPLETE & TESTED (2026-06)
Operational chain: Accepted Quote/Package → Job → Job Material Plan → Inventory Reservation → Shortage → Supplier Comparison → Draft PO → explicit submission. No supplier order is auto-submitted.
- **Architecture**: Quote → Job → JobMaterial → InventoryTxn (reservation ledger) → PurchaseOrder → POLineItem → Supplier. Reservations use `InventoryTxn(reason="job_reservation", job_id)` (negative delta); release nets positive. Reservation raises Reserved / lowers Available; NEVER changes physical On Hand (On Hand changes only on receive/issue).
- **Migration `f6a7b8c9d0e1`** (down `e5f6a7b8c9d0`): additive — `job_materials` + unit, source_quote_id, source_quote_line_id (idempotency key), assembly_id, assembly_name.
- **Calc (services/job_planning.py, server-authoritative)**: Required = JobMaterial.planned_quantity (snapshot from accepted quote/package; never recalculated); Reserved/Issued/Returned = |Σ ledger by reason|; Ordered/Received = Σ POLineItem qty/received for POs linked to THIS job; JobIncoming = Σ max(qty-received,0) over OPEN job-linked POs (cancelled/received excluded); Shortage = max(Required − Reserved − JobIncoming, 0); Remaining = max(Required − Issued, 0). Readiness: ready / partially_ready / waiting_on_materials / backordered (shortage alone ≠ backordered). Only job-linked POs count toward a job's incoming.
- **APIs**: `GET /jobs/{id}/material-plan`, `POST /jobs/{id}/materials/generate` (idempotent from accepted quote/accepted package only; material-linked lines only), `POST .../materials/{jm}/reserve` (caps at available & outstanding), `POST .../materials/{jm}/release`, `GET /jobs/{id}/purchase-proposal` (shortage lines + full supplier comparison: preferred/best/all active mappings w/ cost, freshness, UOM, conversion, lead time). `GET /api/inventory/reorder-suggestions` (projected<threshold, recommends replenishment, returns preferred_supplier_id — never auto-orders). PO status vocabulary normalized (draft/ready_for_review/ordered/submitted/acknowledged/scheduled/partially_received/received/backordered/cancelled); ABC raw status preserved separately in abc_order_status/abc_normalized_status. Existing PO GET/{id}, /status, /receive, ABC submit-review/submit reused unchanged.
- **UI**: JobDetail "Job materials" → `JobMaterialPlan` (plan table Required/Reserved/Available/Shortage/Ordered/Received + readiness badges, Generate from quote, Reserve/Release, Create-PO-for-shortages proposal dialog grouping by supplier and creating draft POs linked to the job). New `/purchase-orders/:id` PO detail page (header/supplier/integration/lines/receiving, Mark-ordered for manual drafts, Receive partial, Cancel). Inventory → Reorder Suggestions dialog → draft POs grouped by preferred supplier.
- **Idempotency/Audit**: generate deduped by source_quote_line_id; reservations net via ledger; receive has idempotency-key support; generate/reserve/release/PO status all audited.
- **Tests**: `tests/test_job_material_automation.py` 6 pass (idempotent generate, snapshot-waste Required, reservation-does-not-change-on-hand, proposal shortage+suppliers, reorder endpoint, unrelated-PO-not-counted). Regression: phase3 14, phase5 7 pass. Frontend testing_agent iteration_36 = 100% backend & frontend, zero bugs.
- **Known limitations / scope notes**: The job purchase-proposal and reorder create **manual-style draft POs**; ABC electronic submission remains via the existing ABC order panel (not wired into the proposal). Reservations are not auto-released on job close/cancel (manual release). Advanced inventory locations/transfers/job costing NOT started (deferred).

## Actual Job Costing — COMPLETE & TESTED (2026-06)
Connects immutable historical estimate/quote snapshots to actual operational consumption. Estimated-vs-actual cost, gross profit & margin, secured from Sales (server + UI). Decimal/NUMERIC(14,4) throughout — no float drift.
- **Cost basis**: Moving Weighted Average Cost (MWAC) on `materials.avg_cost` (NUMERIC(14,4), NULL=no basis). Recomputed only on PRICED receipts (unit_cost>0); unpriced receipts leave MWAC untouched. `inventory_txns.unit_cost`/`extended_cost` (NUMERIC) are immutable per-txn snapshots (receipt/issue/return/waste). Issue & waste snapshot current MWAC (final — never revalued when MWAC later changes). Returns reverse cost at the weighted-average of outstanding issued cost for that job+material, and fold that basis back into MWAC. Migration `b1c2d3e4f5a6` (additive).
- **Baseline** (`services/job_costing.estimated_baseline`): primary = accepted quote/package internal cost snapshot (`QuoteLineItem.total_unit_cost` × qty, per material); category detail from linked Estimate; fallback status `estimate`; `none` (No Estimate Baseline) when neither has historical cost. Never recomputed from live prices.
- **Manual actual costs** (`actual_cost_entries`): categories labor/equipment/subcontract/permits/disposal/other + description/notes/amount (NUMERIC). **Immutable completion snapshot** (`job_cost_snapshots`) auto-captured when a job → completed (also manual via API). Migration `c2d3e4f5a6b7` (additive).
- **Summary** (`job_costing.summary`): revenue=sold price; estimated vs actual by category + total; variance; estimated & actual gross_profit/margin%; costing_status = no_estimate_baseline | missing_cost_basis | complete(job completed) | partial | not_started.
- **RBAC**: `GET /api/jobs/{id}/costing`, `GET/POST/DELETE /api/jobs/{id}/actual-costs`, `GET/POST /api/jobs/{id}/cost-snapshots`, and all `/api/reports/costing/*` require owner/administrator/office. Sales → 403. `/api/inventory/transactions` hides unit_cost/extended_cost from Sales. UI: Costing section + Reports page client-gated too (defense-in-depth).
- **Reports** (`routers/reporting.py`, `/api/reports/costing/*`): profitability (per-job), material-variance (cross-job), waste (waste/damage/loss cost by material), supplier-impact (received cost by supplier).
- **UI**: `components/JobCosting.jsx` (Costing section on JobDetail: status badge, headline stats, estimated-vs-actual table, material variance, manual cost add/delete, snapshot capture, data-quality warnings). `pages/Reports.jsx` (4 tabs) wired at `/reports` (was Placeholder).
- **Tests**: `tests/test_job_costing_batch{1,2,3_rbac,4_reports}.py` — 19 pass +1 skip. Full regression (advanced inventory, job automation, estimating, phase5, inventory core) 64 pass +1 skip. Frontend testing_agent iteration_39 = 100% (7/7 flows, sales RBAC verified), zero bugs.
- **Guardrails honored**: reservations & open POs never actual cost; supplier price changes after receipt/issue never revalue basis/job cost; historical estimate/quote snapshots immutable; no accounting/payroll/QuickBooks/COGS added.

## Purchasing / Pricing / Customer-Output Completion — COMPLETE & TESTED (2026-06)
Operational gaps + customer-facing pricing/output. No payroll/timekeeping/QuickBooks/COGS added.
- **PO Status History** (`po_status_history`, migration `d3e4f5a6b7c8`): real events written only on meaningful normalized-status change (no dupes on repeated sync); raw ABC provider status stored separately; existing POs seeded ONE `imported` current-state baseline (not backdated). `record_status()` wired into create/set_status/receive/ABC submit+refresh. `GET /api/purchase-orders/{id}/status-history`. UI: real timeline on PO Detail.
- **Receiving Attachments**: reuse existing Photo infra (`/api/mobile/photos`, record_type `purchase_order` added to whitelist; categories packing_slip/receipt/delivery_photo/damage_photo/other). Optional. UI: `ReceivingAttachments` + `PhotoGallery` on PO Detail.
- **Price Book Auto-Application** (`services/pricing.py`): deterministic priority exact-material → assembly → general(no material/assembly) → manual (NO invented fallback). Rules fixed/markup/margin. New estimates default to active/default price book; explicit user pricing always wins. Applied book+rule snapshotted on line (`applied_price_book_id/type/value`, migration `d3e4f5a6b7c8`). Existing estimates never silently repriced — `POST /estimates/{id}/price-book/preview` + `/apply` with review dialog. `Estimate.price_book_id` added.
- **Customer Proposal** (`services/proposal.py`, ReportLab): `GET /api/quotes/{id}/proposal` (customer-safe JSON) + `/proposal.pdf` (real PDF). Built ONLY from stored quote/package snapshot; NEVER reads supplier/material cost, markup, margin, best-known-cost, internal notes, or live prices. Good/Better/Best packages render cleanly, selected package flagged, acceptance shown. `FIELD_ROLES` (incl. sales) may generate — output is customer-safe. UI: `ProposalPreview` page (`/quotes/:id/proposal`) + Preview/PDF buttons on Lead Detail quotes.
- **Company Branding**: extended `company_profile` config (schema-only, no migration) with `logo_url/website/proposal_footer_text/proposal_terms_text` (all optional; graceful text-only fallback). UI: Settings > Company Profile.
- **Margin Guardrails** (`margin_policy` config; `GET/PUT /api/margin-policy`, MANAGE roles): default enabled=false, target=30%. Warning-only — never blocks save/quote/accept, never on customer output. Surfaced in estimate `margin_warnings` (cost-gated) + Estimate Editor banner. UI config in Settings.
- **Cost Overrun Alerts**: `summary.alerts` (over_budget, total/material/other overrun amount+%). UI: red banner on Job Costing; negatives red on Reports.
- **Cost Snapshot History UI**: `GET /jobs/{id}/cost-snapshots/{snap_id}`; Job Costing shows immutable snapshot history table + view dialog.
- **CSV Export**: `/api/reports/costing/{profitability|cost-variance|material-variance|waste|supplier-impact}.csv` (UTF-8, quoted), MANAGE-only; Sales 403. UI: Export CSV per Reports tab.
- **RBAC**: all cost/margin/profitability/report/CSV endpoints owner/administrator/office only; Sales 403 (server-side). Customer proposal endpoints return only customer-safe data.
- **Tests**: `tests/test_purchasing_pricing_output.py` 11/11; Job Costing 4 batches 19 pass +1 skip; Estimating modernization 12/12; ABC P3 21/21 (serial); frontend testing_agent iteration_40 = 100% (9/9 flows, one Reports.jsx missing-import bug found & fixed). Known: `test_advanced_inventory::test_issue_consumes_reservation_and_reduces_onhand` flakes on the shared dev DB because repeated transfer-test runs scatter an arbitrary material's stock across accumulated QA-yard locations (env data artifact, not a code regression; passes on clean DB).

## Final UX / Security / Data-Integrity / Regression Hardening — COMPLETE (2026-06)
Pre-final-validation hardening. No new business features. Only backend TEST files changed this phase (no production code), plus doc updates.
- **Test isolation (Part 1)**: `tests/test_advanced_inventory.py` fixtures now self-own their data — `_stocked_material()` creates a brand-new material and receives stock to the DEFAULT location via a manual PO; `_accepted_job()` builds on it. No dependence on arbitrary preview-DB materials or execution order. Verified deterministic across 3 parallel + 1 serial runs (11/11 each). Assertions unchanged.
- **Legacy suite fix**: `tests/phase4_test.py` used the retired adjust reason `stock_in` (rejected since the Inventory Core refactor's `TXN_TYPES` allowlist) → changed to valid `adjustment`. Suite now 19/19 (serial + loadscope-parallel).
- **Full backend regression**: non-ABC suite **400 passed / 19 skipped**; ABC (per-file own-process, serial) **118 passed / 1 skipped**. Grand total **518 passed**. Remaining non-green are pre-existing & unrelated to this modernization: `test_location_resolution_pipeline` (3, map/geocoding structural), `test_maptiler_geocoding` (collection error: optional dep `mapbox_vector_tile` not installed), `test_inventory_core_hardening::test_db_rejects_two_active_preferred` (self-owned test; passes in isolation, intermittent only under heavy parallel asyncpg-pool contention). ABC-API suites are documented per-file-serial (shared in-process mock order store).
- **Frontend regression (Part 22)**: testing_agent iteration_41 = **100%**, zero UI/integration/design issues across Inventory, Locations, Transactions, Suppliers, Product Catalog, Estimates, Price Books, Quotes/Proposal (cost-leak scan clean), Jobs/Costing (overrun + snapshot history), Purchasing (timeline + attachments), Reports (CSV), Settings, and RBAC (Sales blocked from costing/reports; proposal customer-safe).
- **Audits confirmed via existing green suites**: RBAC (test_inventory_ops_rbac, test_job_costing_batch3_rbac, purchasing/phase4 RBAC — Sales 403 server-side on cost/margin/profitability/CSV); inventory invariants (on_hand=Σbalances, available=on_hand−reserved, transfer nets 0, single-count receive/issue/return, reservation no-op — test_advanced_inventory/test_inventory_core_*); financial integrity (Decimal/NUMERIC, immutable snapshots — costing batches/estimating); proposal data-leak (customer-safe JSON+PDF asserted, all roles); idempotency (phase4 idempotent receive, ABC duplicate-submit protection); supplier secrets (ABC OAuth encrypted, never returned — ABC suites).

## FINAL END-TO-END ACCEPTANCE — PASSED (2026-06)
Final gate. New self-owned E2E suite `tests/test_final_e2e_acceptance.py` (31 scenarios) covers Material→SupplierMaterial(ABC+manual)→Assembly→Estimate(waste/UOM 3BDL=1SQ/price-book/margin)→Quote→Proposal(HTML+PDF, zero cost-leak)→Accept→Job→Material Plan→Reserve→Shortage→PO→ABC submit(dup-protected)→partial+remainder receive(dup-protected)+attachment→Transfer→Issue(immutable unit-cost snapshot)→Return(historical basis)→Waste→Complete(immutable JobCostSnapshot)→Estimated-vs-Actual costing→Transaction history→Audit + edge cases + Sales RBAC 403.
- Result (testing_agent iteration_42): backend **100% (31/31 E2E + 60/60 regression spot-check, 1 skipped, 0 failures)**; frontend **100%** (all modernized routes load, no error boundaries).
- Backend full suite this session: non-ABC 400 passed / 19 skipped (+31 new E2E = 431 modernization/core passed, 0 failures); ABC 118 passed / 1 skipped (per-file serial). Pre-existing/env non-green (unrelated to modernization): 3 map-domain `test_location_resolution_pipeline`, `test_maptiler_geocoding` collection error (optional dep `mapbox_vector_tile`), 1 asyncpg-pool concurrency artifact in `test_inventory_core_hardening` (passes isolated).
- Confirmed invariants: on_hand=Σbalances; available=on_hand−reserved; transfers net 0; receive/issue/return move once; reservations no-op on_hand; immutable estimate/quote/issued-cost/job-cost snapshots. Security: ABC secrets encrypted & never returned/logged; Sales 403 on cost/margin/profitability/reports/CSV; proposals customer-safe; explicit ABC submission with duplicate protection. Git head d930d51.

## Original Modernization Spec Closure (Prompt 6 gaps) — COMPLETE (2026-06)
- **Purchasing/Inventory Intelligence Dashboard** (extended main Dashboard, no redundant page): `services/dashboard.py` + `GET /api/dashboard/purchasing`. Cards from REAL data: Inventory Value = Σ(on_hand × avg_cost) labeled "Operational (MWAC)" (not GAAP); Low Stock (projected < reorder threshold, honors incoming); Reserved (qty + value); Open POs (open normalized statuses, committed value); Incoming 7d (real expected_date only); Jobs Short (real Job Material Plan shortage via job_planning.rollup); Backordered (only status=='backordered'). "Action required" list (job shortage, PO partial/backordered/overdue) each linking to detail. Cost/value fields gated to owner/admin/office; Sales gets counts only.
- **Inventory On-Hand report** `GET /api/reports/inventory/on-hand[.csv]` (Material/SKU/Category/On Hand/Reserved/Available/On Order/Required/Projected/Avg Cost/Value; cost cols + CSV MANAGE-only, Sales 403).
- **Verified already-implemented (no duplication)**: Reorder Suggestions (projected-aware, reuses reorder service — Part 3 ✅); procurement readiness states ready/partially_ready/waiting_on_materials/backordered in job_planning (Part 4 ✅); Job Material Variance = /reports/costing/material-variance; Material Waste = /reports/costing/waste; Supplier Spend = /reports/costing/supplier-impact; Inventory Transactions page; PO list (open/history).
- **N/A (documented)**: Supplier Performance delivery metrics — insufficient promised/delivered timestamps in current data; surfaced as "unavailable until delivery-history captured" per the original guardrail rather than fabricated.
- Tests: `tests/test_spec_closure_dashboard.py` 4/4; modernization regression 106 passed/1 skipped; frontend iteration_43 = 100%. Git head 6e26a16.

## Emergent Runtime/Build Decoupling — COMPLETE (2026-06)
Removed all Emergent PRODUCTION dependencies so RoofSpan builds/runs on a plain Windows/PyPI machine.
- `backend/requirements.txt`: removed `emergentintegrations==0.2.0` and the private-URL `litellm @ https://customer-assets.emergentagent.com/...` wheel. Neither is imported anywhere in code (0 production/test usages).
- Verified: clean venv `pip install --no-cache-dir --index-url https://pypi.org/simple -r backend/requirements.txt` = PASS (all deps from PyPI, zero Emergent/private URLs); clean-venv `import server` = PASS; backend regression testing_agent iteration_44 = 100% (71/71), zero issues.
- Audit classification: `windows/*` → only doc/comment mentions of "Emergent" (metadata, not deps); build scripts install `-r backend/requirements.txt` (now public). `frontend/package.json @emergentbase/visual-edits` (assets.emergent.sh) → DEV-ONLY visual editor, already craco-optional (graceful MODULE_NOT_FOUND), not a RoofSpan runtime/build requirement. `.preview.emergentagent.com` in `.env`/tests/frontend → ENV/dev metadata (URL injected via env var, not packaged). `.emergent/` cron scripts → dev metadata, not packaged/executed by runtime.
- PyInstaller 6.22.2 resolves from public PyPI; no Emergent hidden imports remain. Windows freeze (build_exes.ps1) + stage.ps1 are PowerShell/Windows-only (run on the Windows build host) but have no remaining Emergent blocker.
- **RE-REMOVED 2026-08:** a `pip freeze` had silently re-added `emergentintegrations==0.2.0` and the private-URL `litellm` wheel to `backend/requirements.txt` (both still 0 imports — verified via `grep -rIn -E "^\s*(from|import)\s+(emergentintegrations|litellm)"` = 0). Removed both again; backend runs healthy without them. ⚠️ GUARD: never `pip freeze > requirements.txt` in an env where these are installed — it reintroduces the private-repo build blocker. Add/remove deps by hand.

## Mobile Expo/EAS Project Linkage Fix — DONE (2026-08)
Config-only change in `mobile/app.json` to link the local project to the existing Expo/EAS project (owner `armyjake75`, slug `roofspan`, projectId `edcd6d6d-f0e9-49a0-8fd1-0ba39ff11bef`).
- `slug`: `roofspan-field` → `roofspan`; added `"owner": "armyjake75"`; added `extra.eas.projectId`.
- `extra.apiBase`: `https://unified-mono-deploy.preview.emergentagent.com` → `https://cp.roofspan.io` (authoritative production Control Plane base per `infra/config/production.endpoints.env.example` + `mobile/src/config.js`; not invented). Build-time `EXPO_PUBLIC_CONTROL_PLANE_BASE_URL` still overrides.
- Preserved unchanged: iOS/Android identifiers `io.roofspan.field`, adaptive icon, plugins, scheme, version; `eas.json` (`appVersionSource: remote`, `production.autoIncrement: true`).
- Validation: `expo config --json` reports slug=roofspan, eas.projectId=edcd6d6d…, ios/android=io.roofspan.field. All 5 mobile test suites pass. `expo-doctor`: only pre-existing package-version advisories (expo-camera major + 3 patch) — NOT touched (task forbids dep/SDK upgrades). `eas project:info` needs Expo auth (unavailable here) → run locally.

## Mobile EAS Build Fix — Missing babel-preset-expo — DONE (2026-08)
- **Root cause:** `mobile/babel.config.js` requires `babel-preset-expo` but it was NOT a declared dependency in `mobile/package.json` (present only transitively via `expo`). Clean EAS install (no cache) couldn't guarantee resolution → `expo export:embed` Babel stage failed.
- **Fix:** `npx expo install babel-preset-expo` (npm) → added `"babel-preset-expo": "~54.0.10"` (resolves to 54.0.12, SDK-54 compatible). Removed stray `mobile/yarn.lock` and generated `mobile/package-lock.json` so there is a single npm lock file (task-mandated npm workflow; not converted to yarn/pnpm). `babel.config.js` reviewed — valid for SDK 54, unchanged.
- **Validation:** `npm ci` OK; `npm list babel-preset-expo` resolves (direct + deduped 54.0.12); `expo install --check` shows only pre-existing expo/expo-camera/expo-constants/expo-file-system advisories (babel-preset-expo NOT flagged). `expo export --platform android`: Metro/Babel bundled ALL 1008 modules successfully (the original failing stage is fixed); it then fails only at the OPTIONAL Hermes bytecode step because this sandbox is **aarch64** and RN ships x86-64 `hermesc` (`linux64-bin`) → `Exec format error`. This is an ARM64-container limitation, NOT a code/config defect; EAS Android builders are x86-64 where hermesc runs. All 5 mobile tests green. `expo-doctor`: same pre-existing version advisories only. `jsEngine` left as-is (not changed to jsc — out of scope).

## Fix: Office "Connect Mobile Device" 500 on CP /activate — DONE (2026-08)
- **Symptom:** Office Mobile Access → Connect Mobile Device → `Could not reach RoofSpan Control Plane to pair device: 500 for .../api/control-plane/activate`.
- **Root cause:** First-time CP activation issues an entitlement, which needs an ACTIVE Ed25519 signing key. In LOCAL (non-KMS) mode, key creation called `keys._mirror_to_disk()` writing to `CP_DEV_SIGNING_KEYS_DIR` (defaults to a dir *inside the code bundle*). On the packaged/frozen Windows build that dir is read-only, so `os.makedirs`/`open`/`os.chmod` threw. `init_control_plane()` runs `ensure_active_key()` at startup with no error handling → no key was ever created → the first `/activate` retried creation, hit the same disk error, and the CP router (only mapping `CPError`) returned an unhandled **500**. (Bootstrap-credential mismatch would be 401, not 500, so ruled out.)
- **Fix:** `control_plane/keys.py::_mirror_to_disk` is now best-effort (try/except + warning log) — the authoritative private key is in the isolated CP DB; the disk mirror is a dev convenience and must never break activation. `os.chmod` wrapped separately (POSIX-only). `control_plane/router.py::activate` now catches unexpected exceptions, logs a full traceback, and returns the real error message instead of a blank 500.
- **Tests:** `tests/test_cp_activation_disk_mirror.py` (2 — activation-time mirror never raises on a read-only dir + still writes when writable) + `test_pairing.py` (8) + `test_pairing_user_binding.py` (7) all green. Backend healthy.
- **Secondary note for prod:** if a local build sets `CP_ENV=production`, `ENTITLEMENT_SIGNER=kms` and activation needs `CP_KMS_SIGNING_KEY_ID` + AWS — the improved router now surfaces that clearly. The embedded co-hosted CP should run in local-signer mode for on-machine installs.

## Fix: Windows CP DB provisioning defect (roofspan_control_plane missing) — DONE (2026-08)
- **Root cause:** `windows/winbuild/db_bootstrap.py` created only the least-privilege `roofspan` role (NOCREATEDB) + the `roofspan` business DB. The embedded Control Plane uses a SEPARATE DB `roofspan_control_plane` (derived in `control_plane/config.py`), and its startup `run_cp_migrations()→ensure_database()` tried to `CREATE DATABASE` as the runtime `roofspan` role → `permission denied to create database` (swallowed non-fatally). Later `/api/control-plane/activate` hit the missing DB → `InvalidCatalogNameError` → 500 → Office pairing 502.
- **Fix (provision + repair via superuser; role stays least-privileged):**
  - `db_bootstrap.py`: superuser step now creates BOTH `roofspan` and `roofspan_control_plane`, each `OWNER roofspan` (`_create_db_if_missing` + `_own_public_schema`). Role is now explicitly `NOSUPERUSER NOCREATEDB` (revokes CREATEDB if a prior build granted it). New idempotent `_ensure_cp_db_only()` + `repair_control_plane_db()` (decrypts existing DPAPI superuser secret, waits for PG, creates CP DB if missing). `bootstrap()` early-return (already-provisioned) path now runs the repair — so EXISTING installs are fixed on next backend start. No credential/JWT/encryption-key/identity rotation; no data touched.
  - `server.py`: CP-init failure now logs the FULL traceback (was a one-line warning) while staying non-fatal.
  - `licensing/pairing_client.py`: replaced `raise_for_status()` (all 4 CP calls) with `_raise_for_cp()`/`ControlPlaneError` that surfaces a SAFE `detail` from the CP (secret-hint scrubber blocks connection strings/passwords/keys/JWTs) → Office Mobile Access shows a useful message instead of a bare 500.
- **Tests:** `tests/test_windows_cp_db_bootstrap.py` (4: fresh creates both DBs owned by roofspan + role NOSUPERUSER/NOCREATEDB via superuser only; existing role kept & forced least-privilege; repair creates missing CP DB; repair preserves existing CP DB + idempotent; asserts CREATEDB never granted). Regression: `test_pairing.py` 8, `test_pairing_user_binding.py` 7, `test_cp_activation_disk_mirror.py` 2 — all green (21 total). End-to-end: Office `POST /api/admin/users/{id}/mobile/pair` returns numeric_code + qr_payload.token + expected_user binding.

## Material cost columns migration + Receiving bug fix — DONE & VERIFIED (2026-06)
- **Root cause of "Receive doesn't update qty-on-hand / doesn't close the PO":** `models.py` declared `materials.standard_cost` + `materials.default_sell_price` (Numeric(14,4)) but no migration existed, so the DB was missing those columns. Every Material read/write — including `POST /purchase-orders/{id}/receive` (which does `select(Material)...with_for_update()`) — threw a 500 (`UndefinedColumnError: column "standard_cost" ...`). Receiving therefore never posted inventory or advanced PO status.
- **Fix:** added additive migration `e6f7a8b9c0d1` (down_revision `d3e4f5a6b7c8`) adding `standard_cost` + `default_sell_price` (NUMERIC(14,4), NULLABLE). Applied cleanly; alembic head now `e6f7a8b9c0d1`. No frontend/endpoint code changed — the receive logic was already correct.
- **Verified end-to-end (curl + preview UI):** full receive (10/10) → PO `received`, on-hand 10; partial (4/10) → `partially_received`, on-hand 4; remainder (6/10) → `received`, on-hand 10. Preview PO tab shows the `received` badge.
- **Fork env recovery:** this forked pod came up with a fresh PostgreSQL (role `roofspan` + DB missing). Bootstrapped role/DB, started postgres + supervisor, raised inotify watch limit; migrations then applied to head.
- **STILL PENDING (from prior handoff, not yet started):** the broader "Material Create Form + Full Material CRUD" work (create-form fields SKU/Purchase UOM/Conversion/Standard Cost/Default Sell Price; Material Detail Edit/Deactivate/Delete with safe-delete + edit-safety; Sales cost-gating). Migration prerequisite is now DONE.


## ABC Catalog manufacturer/brand mapping bug fix — DONE & VERIFIED (2026-06)
- **Report:** "manufacturer is not showing up on the ABC catalog after sync, and isn't set on items when adding to / updating inventory."
- **Root cause A (wrong field names):** `map_catalog_fields` read `item.get("manufacturer")` / `item.get("brand")`, but the REAL ABC Product API item payload has **no** such keys. Per ABC docs (confirmed via integration_expert): manufacturer = top-level `item.supplierName`; brand = nested `hierarchy.productGroup.category.productType.materialComposition.warranty.brandLine.label`. So on real ABC both mapped to `None` → blank in catalog.
- **Root cause B:** `catalog_add_to_inventory` stuffed manufacturer only into `abc_metadata` and **never set the top-level `Material.manufacturer`/`brand` columns** — so added materials showed no manufacturer; the existing-link path didn't update it either.
- **Fix (backend only):**
  - `integrations/abc_supply/catalog.py`: new `_manufacturer()` (`supplierName` → legacy `manufacturer` fallback), `_brand()`/`_brand_line()` (deep-guarded `brandLine.label`→description→name, fallback to `brand`/manufacturer). `map_catalog_fields` uses them.
  - `routers/abc_supply.py::catalog_add_to_inventory`: new materials now set `manufacturer=cat.manufacturer, brand=cat.brand`; existing-link path backfills `manufacturer`/`brand` only when missing (never clobbers user-curated values).
  - `integrations/abc_supply/mock_server.py`: mock items updated to the real schema (`supplierName` + a nested `brandLine` on the shingle) so the pathway is exercised.
- **Verified end-to-end (mock, curl):** catalog sync → shingle shows mfr `MockBrand` / brand `MockBrand Timberline HD`; add-to-inventory fresh create AND existing-link backfill both populate `Material.manufacturer`/`brand`; mapping unit-checked for real ABC (`supplierName=GAF`, `brandLine.label=GAF Timberline HD`), legacy fallback, and sparse/missing-hierarchy (no 500). ProductCatalog UI already has Manufacturer column + manufacturers facet → now populated automatically. No migration needed.


## Price Book targeting (Supplier/Manufacturer/Category/Item/Default) + Material effective Cost & Price — DONE & VERIFIED (2026-06)
- **Request:** Price Book entries should target Supplier / Manufacturer / Category / specific Item / Default, and the matching rule should produce the **Price** shown on each inventory material (alongside **Cost**) — which was previously not surfaced on the material.
- **Migration `f7a8b9c0d1e2`** (down `e6f7a8b9c0d1`): adds `supplier_id` (FK suppliers, CASCADE), `manufacturer`, `category` to `price_book_entries`. `target_type` now `material | supplier | manufacturer | category | default | labor | assembly`. Additive; existing entries untouched.
- **Cost basis (`services/pricing.resolve_effective_cost`)**, in order: preferred supplier cost → best known cost → `standard_cost` → MWAC `avg_cost` → none. Returns `effective_cost`, `effective_cost_source` (preferred_supplier|best_known_cost|standard_cost|mwac) + the cost-source `supplier_id`/`name`. avg_cost/standard_cost are NEVER rewritten by supplier/price changes.
- **Rule resolution (`resolve_material_rule`)**, most-specific-wins: Item → **Supplier (must equal the cost-source supplier, not any cheaper mapping)** → Manufacturer → Category → Default. **Default Price Book only** (never an implicit "only active book"); if no default, price is null (explicit missing-default). Decimal/NUMERIC math; markup `cost*(1+p/100)`, margin `cost/(1-p/100)` kept distinct. `compute_material_pricing` returns `effective_price` + `price_book_id/name` + `matched_rule_id/type/label`. Missing all cost → `effective_cost=null` & `effective_price=null` (never fabricates $0).
- **`services/pricing.find_rule` (estimates) fixed**: supplier/manufacturer/category entries are no longer mistaken for the estimate default (new `_is_default_entry`). Existing labor/assembly/material estimate behavior + historical snapshots unchanged (verified: estimating suite 12/12).
- **RBAC:** `list_materials` + `material_detail` strip ALL cost fields for Sales (`effective_cost`, source, supplier cost, best_known, standard_cost, matched_rule_label, and detail supplier `current_cost`) via `_strip_cost_for_sales`; **Price stays visible to Sales**.
- **Schemas:** `MaterialIn`/`MaterialPatch` now accept `standard_cost`/`default_sell_price`; `MaterialListItemOut` carries the effective cost/price + provenance. Estimating `PriceBookEntryIn/Out` carry supplier_id/manufacturer/category (+supplier_name).
- **UI:** PriceBooks entries editor gains the 5 material target types (supplier→/suppliers dropdown, manufacturer/category→facets, item→materials, default→fallback note) keeping labor/assembly. Inventory materials list adds a **Price** column (Cost=effective_cost, Price=effective_price, `—` when null). Material Detail shows Cost card (source, e.g. "Preferred Supplier — ABC Supply") + Price card ("Price Book: Standard · Rule: …"); Cost card hidden from Sales.
- **Tests:** `tests/test_material_pricing.py` 7/7 (priority cascade, supplier aligned to cost source, preferred-over-cheaper, best-known, standard, mwac, missing→null, default-book-only vs 999% non-default ignored, markup+margin, inventory+detail expose Cost+Price, Sales cost-gated + price-visible, labor/supplier entries persist). Estimating regression 12/12. curl + UI screenshots confirm end-to-end.
- **NOTE:** dev DB accumulated many throwaway price books from testing; harmless. Sales test user `sales@example.com` / `SalesRS#2026`.

## Material Detail full CRUD (Edit / Adjust / Deactivate / Safe-Delete) — DONE & VERIFIED (2026-06)
- **Request:** clicking a material from Inventory must allow editing its details (full CRUD).
- **Backend:** new `DELETE /api/materials/{id}` (MANAGE roles) = **safe delete** — hard-deletes only when the material has NO references and NO on-hand stock; otherwise `409` with a message listing what blocks it (supplier mappings, inventory txns, estimate/quote/PO lines, job plans, assembly items, price-book entries, ABC catalog links, on-hand stock) and tells the user to Deactivate. On delete, `inventory_balances` cascade. Edit uses existing `PATCH /materials/{id}` (now accepts standard_cost/default_sell_price/etc.); Deactivate = `PATCH active`. Editing never mutates historical estimate/quote/PO/job snapshots.
- **UI (`MaterialDetail.jsx`):** action bar (data-testid `material-actions`) with `edit-material-button`, `adjust-inventory-button`, `toggle-active-button` (Deactivate/Reactivate), `delete-material-button` (window.confirm + 409 toast → suggests Deactivate). Edit dialog (`edit-material-dialog`) fields: name, sku, category, manufacturer, brand, unit, reorder_threshold, standard_cost, default_sell_price, description. Adjust dialog reuses the structured TXN_TYPES dropdown. All gated to MANAGE roles.
- **Verified (curl + UI):** delete no-refs → 200; delete with supplier mapping → 409 ("1 supplier mappings … Deactivate instead"); delete with on-hand stock → 409; PATCH edit → 200 and fields persist (mfr=GAF, standard_cost=12.5, category=Roofing); Edit dialog opens pre-filled, Cost card shows "Source: Standard Cost".
- **NOTE (infra):** the forked pod's supervisord/postgres died mid-session twice; restarted via `supervisord -c /etc/supervisor/supervisord.conf` (it manages backend/frontend/postgres/mongo). If backend returns 000, re-run that.


## Inventory UX pack: Create-form parity, Edit-from-list, Undo-deactivate, Supplier editor — DONE & VERIFIED (2026-06)
- **Create Form Parity (Inventory.jsx "Add material"):** added SKU, Purchase UOM (`purchase_unit`), Conversion (`conversion_factor`, validated >0 when a purchase UOM is set, with helper text), Standard cost, Default sell price (+existing Category/Stock UOM/Qty/Reorder). Backend `Material(**data)` persists all (verified: detail shows standard_cost/default_sell_price/sku; create response uses leaner MaterialOut so those show null there — cosmetic only, list/detail refetch shows them).
- **Edit From List:** each Inventory materials row now has **Edit** + **Adjust** buttons (`edit-{id}` / `adjust-{id}`); Edit opens `inv-edit-dialog` (name, sku, category, manufacturer, brand, unit, standard_cost, default_sell_price, reorder) → `PATCH /materials/{id}`.
- **Undo Deactivate Toast (MaterialDetail.jsx):** deactivating shows a sonner toast with an **Undo** action that re-`PATCH`es `active:true`. Reactivate path unchanged.
- **Supplier Mapping Editor (MaterialDetail.jsx):** "Add supplier" button (`add-supplier-button`) + per-row pencil (`edit-supplier-{smId}`) open `supplier-dialog`. Add → `POST /supplier-materials` (supplier select from /suppliers, item#, UoM, cost); Edit → `PATCH /supplier-materials/{smId}` (item#, UoM, cost). Cost change re-snapshots price history + sets price_status manual (existing backend behavior) and immediately feeds the material's effective Cost/Price.
- **No new backend endpoints** — all four reuse existing routes. Verified via curl (create persistence, supplier add + cost edit 200) and preview UI screenshots (all dialogs render/pre-fill; undo toast visible; supplier editor opens on "ParitySup").


## ⚠️ INFRA — correct Postgres is the PERSISTENT cluster (read before touching DB)
- The real database is the **supervisord-managed** Postgres at data dir **`/data/db/roofspan_pgdata`** (program `[program:postgresql]` in /etc/supervisor/conf.d/postgresql.conf). It holds the user's real data and the `roofspan` role/password matching `backend/.env` DATABASE_URL.
- DO NOT run `pg_ctlcluster 15 main start` — that starts the empty Debian default cluster (`/var/lib/postgresql/15/main`) which then squats on port 5432 and blocks the real one, causing `password authentication failed for user "roofspan"` and backend 000. (I hit this early in the session and unknowingly built/tested against the ephemeral cluster for a while.)
- **If backend returns 000 / auth-fails:** `sudo pg_ctlcluster 15 main stop` (free 5432), then `sudo /usr/bin/supervisord -c /etc/supervisor/supervisord.conf` (or `sudo supervisorctl start postgresql backend frontend`). supervisord itself has died a few times in this fork — just relaunch it. Alembic auto-migrates on backend startup.

## Inventory power-tools: Delete-from-list, Bulk edit, Supplier cost history, Low-stock reorder grouping — DONE & VERIFIED (2026-06)
- **Delete From List:** each Inventory materials row has a red trash button (`delete-{id}`) → reuses `DELETE /api/materials/{id}` safe-delete (409 if referenced/on-hand stock → toast suggests Deactivate).
- **Bulk Edit:** per-row checkboxes (`bulk-select-{id}`) + select-all (`bulk-select-all`); a `bulk-action-bar` appears with count + Bulk edit + Clear. Dialog (`bulk-edit-dialog`) lets you tick Category / Standard cost / Reorder threshold to change for all selected → new backend `POST /api/materials/bulk-update` (MANAGE roles; only fields present in body are applied via `model_fields_set`; 400 if no ids/fields).
- **Supplier Cost History:** the Material-Detail supplier editor (edit pencil) fetches `GET /supplier-materials/{sm_id}/price-history` and renders a `Sparkline` SVG (needs ≥2 points) + a dated list with source. Verified: 3-point chart ($11.50/$12/$10) draws; empty state shows "No recorded cost changes yet."
- **Low-Stock Reorder:** enhanced existing `ReorderSuggestions` — rows are now grouped by preferred supplier (each group header shows "→ 1 draft PO"); a distinct amber "No preferred supplier (cannot order)" group disables those checkboxes; still creates one draft PO per supplier on submit (nothing auto-ordered). Est. cost column added.
- **Backend:** one new endpoint (`materials/bulk-update`) + schema `MaterialBulkUpdate`; everything else reused. Verified via curl (bulk-update 200 both rows; no-fields 400; delete 200; price-history 3 points) and preview-UI screenshots (470 delete buttons, bulk bar+dialog, grouped reorder, sparkline) — all on the persistent DB.


## Reorder totals, Saved filters, Bulk delete/deactivate — DONE & VERIFIED (2026-06)
- **Reorder Cost Totals (ReorderSuggestions.jsx):** each preferred-supplier group header shows a subtotal (Σ included qty × best_known_cost, `reorder-subtotal-{sid}`) with "→ 1 draft PO"; dialog footer shows a **Grand total** (`reorder-grand-total`) across all included orderable rows. Added an "Est. cost" column per row.
- **Saved Filters (Inventory.jsx):** localStorage-backed (key `roofspan.invFilters.{userId}`). "Save filter" button prompts for a name and stores the current filter combo; a "Saved filters" dropdown recalls them one-click; each entry has an inline remove (×). Verified save → clear → recall restores low-stock filter.
- **Bulk Delete / Deactivate (Inventory.jsx + backend):** selection bar now has **Deactivate** (→ `POST /materials/bulk-update {ids, active:false}`; `active` added to `MaterialBulkUpdate`) and a guarded **Delete** (→ new `POST /materials/bulk-delete`). Bulk-delete reuses the extracted `_material_delete_blockers()` helper: deletes only unreferenced/zero-stock items, returns `{deleted, blocked:[{id,name,reason}]}`; UI toasts "Deleted X; Y kept (have history/stock) — deactivate those instead". Never partially corrupts history.
- **Backend:** new `POST /materials/bulk-delete`; `bulk-update` gained `active`; delete reference-check refactored into shared `_material_delete_blockers`. Verified via curl (bulk deactivate 3→active False; bulk delete 2 deleted + 1 blocked "1 supplier mappings") and UI screenshots (bulk bar Deactivate/Delete, saved-filter save+recall, reorder grand total). Cleaned up my session's test materials on the persistent DB afterward.


## Estimate item pull-in (cost + sell price + qty) — DONE & VERIFIED (2026-06)
- **Request:** on the estimate page, selecting a catalog item should pull the item's unit cost AND sell price onto the line, with an adjustable Qty.
- **Fix (frontend only, `EstimateEditor.jsx`):** `addProduct` now sets `material_cost = effective_cost` (→ primary/best fallback) and `selling_unit_price = effective_price ?? default_sell_price ?? cost`, and computes `markup_percent` from cost→sell so the Markup column is right. Previously it set sell = cost (0% markup, no sell price). Qty (Measured) was already editable and recomputes the line/summary.
- **ProductPicker** now shows dedicated **Unit cost** (effective_cost, cost-role only) and **Sell price** (effective_price → default_sell_price) columns so the values are visible before adding.
- **Verified (UI):** picker shows Unit cost $40 / Sell price $60 for a test item; adding it created a line with cost 40, markup 50%, sell 60; setting Qty→4 gave Line Total $240 and updated the estimate summary (Est cost $160, GM 70.37%). Backend unchanged (material lines + cost snapshot already existed); historical snapshot immutability preserved.


## Manual Price override (Cost/Price relabel + Custom flag) — DONE & VERIFIED (2026-06)
- **Rule:** on material forms, `standard_cost` = **Cost** and `default_sell_price` = **Price**. If only Cost is entered → Price is auto-calculated from the Default Price Book applied to Cost. If a Price is entered → it **overrides** any Price Book rule and the item's Price is flagged **Custom**.
- **Backend (`compute_material_pricing`):** now checks `material.default_sell_price` FIRST — if set, `effective_price = default_sell_price`, `price_is_custom = True`, `matched_rule_label = "Custom price (manual override)"` (returned even when there's no cost basis, since it's deliberate). Otherwise falls through to the existing cost→Default-Price-Book computation (`price_is_custom = False`). New `price_is_custom` field added to `MaterialListItemOut` (not cost-gated — visible to Sales).
- **Frontend:** Edit (MaterialDetail + Inventory) and Create forms relabeled to **Cost** / **Price** with helper text ("Leave Price blank to auto-calculate from the Price Book. Entering a Price overrides it, flagged Custom."). Inventory list Price cell + Material-Detail Price card show an amber **Custom** badge and "Custom price — manual override (ignores Price Book)" when overridden. Estimate picker already consumes `effective_price` so overrides flow into estimates automatically.
- **Verified (curl + UI):** cost-only → auto price (custom False); add Price 99 → price 99 custom True; clear Price → back to PB auto; price-only-no-cost → price shows custom True with cost None; UI shows Cost $40 / Price $75 + Custom badge on list & detail, and relabeled Cost/Price fields in edit. Test materials cleaned up.


## Reset-to-Auto price button — DONE & VERIFIED (2026-06)
- Material Detail Price card now shows a one-tap **"Use Price Book price"** button (`reset-price-auto`, MANAGE roles) whenever the price is custom. It PATCHes `default_sell_price:null`, clearing the manual override so pricing returns to the Default-Price-Book calculation.
- Verified (UI): custom $88 → click → toast "Price reset — now calculated from the Price Book", Custom badge removed, price reverts to computed (frontend-only; reuses existing PATCH). Test material cleaned up.

## ABC Live Catalog column relabel Price -> Cost — DONE & VERIFIED by testing_agent (2026-06)
- Bug: the ABC Supply Live catalog table (Inventory -> Product Catalog -> select the "... · Live catalog" source) labeled the pricing column "Price", but ABC pricing is the supplier COST to the contractor.
- Fix (frontend-only, ProductCatalog.jsx): renamed that `<TableHead>` from "Price" to "Cost"; added data-testid `catalog-cost-{itemNumber}` to the cost cell.
- Verified (testing_agent iteration_45.json, 100%): catalog-table headers = [Product, Item #, Manufacturer, UoM, Category, Availability, Cost] — has Cost, no Price. Regression OK: Inventory Materials tab still shows BOTH Cost and Price (intentional). ABC not live-connected in env so body shows mock/—, header is the check and passes.

## Full CRUD on Estimates & Quotes (until accepted) — DONE & VERIFIED by testing_agent (2026-06)
- Request: users can Create/Read/Update/Delete estimates and quotes as long as they are NOT accepted.
- Backend: new `DELETE /api/estimates/{id}` and `DELETE /api/quotes/{id}` (FIELD_ROLES). Guards: quote delete 409 if status==accepted (edit already 400); estimate delete/edit 409 if it has an accepted quote (`_has_accepted_quote`). Line items/packages cascade; a draft quote referencing a deleted estimate survives (FK ON DELETE SET NULL -> estimate_id null).
- Frontend (LeadDetail.jsx): red trash Delete on each estimate row (`delete-estimate-{id}`) and quote row (`delete-quote-{id}`, hidden when accepted), manager roles, window.confirm + toast + reload.
- Verified: testing_agent iteration_46.json 100% (backend 6/6 pytest incl. accepted-guards return 409/400; UI delete flow + accepted-quote delete button hidden). Plus main-agent curl edge case: delete estimate with a DRAFT quote -> 200 and the draft quote survives with estimate_id=null. New test file tests/test_crud_estimates_quotes_delete.py.

## Estimate Duplicate + Undo-delete (estimate & quote) — DONE & VERIFIED (2026-06)
- Duplicate: new `POST /api/estimates/{id}/duplicate` (FIELD_ROLES) copies header + all line items (exact snapshots) into a fresh **draft** with a new number; notes get "(copy)". Verified via curl: EST-0470 (1 item, $108.25) -> EST-0472 draft, items+total copied.
- Undo delete (LeadDetail.jsx, frontend-only optimistic pattern): clicking delete on an estimate/quote row immediately hides it and shows a toast with **Undo** (5s). Undo cancels the pending API call and reloads (nothing was deleted); if the toast expires, the real DELETE fires. Replaces the old window.confirm. Verified in UI: delete hid the row (2->1), Undo restored it (->2).
- Duplicate button `duplicate-estimate-{id}` added to each estimate row. Accepted quotes still show no delete button (prior guard intact).

## BUGFIX: Quote from Estimate always $0 — FIXED & VERIFIED by testing_agent (2026-06)
- RCA: estimate line items store qty/price in variably-populated fields (quantity vs measured_quantity; selling_unit_price vs unit_price). create_quote (routers/quotes.py) read ONLY i.quantity and i.selling_unit_price when snapshotting from an estimate; when those were 0/None (value lived in measured_quantity or unit_price), quote lines saved qty*sell = 0 -> $0 quote.
- Fix: resilient mapping in create_quote -> qty = quantity OR measured_quantity; price = selling_unit_price OR unit_price OR (line_total/qty). Snapshots preserved; no schema change.
- Verified: testing_agent iteration_47.json 100% (backend 4/4 pytest incl. measured_quantity/unit_price fallbacks + multi-line + accepted-guards; full UI E2E: estimate 3 x $100 -> quote QUO-0401 subtotal/total $300, was $0). Regression test: /app/backend/tests/test_quote_from_estimate.py (run with pytest -n 0).

## App Version display + Full Backup/Restore — DONE & VERIFIED (2026-06)
- **App Version (support)**: Fixed a crash on Settings (`Settings.jsx` used `<Copy>` icon without importing it → white-screen ReferenceError). Added the missing lucide `Copy` import. Settings now shows a "Software Version" card (`about-version`/`settings-app-version`) reading `GET /api/version` (e.g. "RoofSpan Office v0.1.0-dev (dev)") with a Copy button; also in sidebar footer. Verified via screenshot.
- **Full Backup/Restore** (Backups page, admin/SENSITIVE_ROLES only): user can create a full portable DB backup, download it anywhere, import an external backup file, and restore ALL data.
  - Service `backend/services/backup.py`: `create_backup()` = `pg_dump -Fc` (atomic .partial→mv) into `ROOFSPAN_BACKUP_DIR` (/data/db/roofspan_backups); `list_backups()`; `resolve_path()` (regex `roofspan_*.dump` + realpath containment — blocks traversal); `save_upload()` validates the `PGDMP` magic header; `restore_backup()` = DROP DATABASE ... WITH (FORCE) + CREATE DATABASE + `pg_restore --no-owner --no-privileges` into the fresh DB. All data lives in PostgreSQL so one dump is a complete backup (photos are in object storage, separate).
  - Router `backend/routers/admin_ops.py`: `GET /api/admin/backups`, `POST /api/admin/backups/create`, `GET /api/admin/backups/download/{filename}` (FileResponse), `POST /api/admin/backups/upload` (multipart), `POST /api/admin/backups/restore`.
  - **KEY FIX (restore hang)**: restoring in-place with `pg_restore --clean` over the live DB hung the async pool and 500'd on dependency teardown. Root causes fixed: (1) restore now DROPs+CREATEs the DB (WITH FORCE terminates live connections) instead of --clean; (2) the restore endpoint authenticates via a SHORT-LIVED session (`_auth_admin`, not `require_roles`) so no `get_db` connection is held for the request lifetime (its teardown was the 500 after the restore killed the connection); (3) `engine.dispose()` before & after so the pool reconnects fresh. After restore the backend is immediately usable (login + queries) with NO manual restart. Audit `backup.restore` is written AFTER the restore so it persists.
  - Frontend `frontend/src/pages/admin/BackupStatus.jsx`: "Create backup now", "Import backup file", backups table (Download / Restore per row), destructive AlertDialog confirm on Restore (reloads app after), plus the existing automatic-backup health card. Test IDs: `create-backup-button`, `import-backup-button`, `backups-list-card`, `backup-item-{filename}`, `download-backup-{filename}`, `restore-backup-{filename}`, `restore-confirm-dialog`.
  - Verified (curl + UI screenshots): create (adds file), download (PGDMP, 1.1MB), upload round-trip (`_import.dump` appears), invalid upload→400, path traversal→404/400, Sales→403 on all endpoints, full restore round-trip (marker material added → restore older backup → count reverts, marker gone, backend recovers cleanly, audit persists), UI create (14→15) + restore confirm dialog.
  - NOTE: env infra hiccup during this session — the app container's supervisord died (socket gone, 502) and did NOT auto-recover; recovered manually via `sudo service supervisor start && supervisorctl reread && update`. If backend is 502 with `/var/run/supervisor.sock no such file`, run that.

## Backup Reminders + Off-site Copy Button — DONE & VERIFIED (2026-06)
- **Off-site Copy**: `POST /api/admin/backups/offsite` (SENSITIVE_ROLES) pushes a chosen local backup to off-pod object storage via the existing `offsite_backup.py put_object` (run in a worker thread), writes a local `<file>.offsite` marker, and audits `backup.offsite`. `list_backups()` now returns `offsite: bool`. UI: per-row "Copy off-site" button (→ "Re-copy off-site" once done) + green "Off-site" badge. Verified via curl (200, object_path returned, flag surfaces) + UI.
- **Backup Reminders**: `BackupStatus.jsx` shows an amber banner (`backup-stale-banner`) with a "Create backup now" CTA when the newest backup is >7 days old or none exist. Purely client-side from the backups list `created_at`; correctly hidden when backups are fresh. Test IDs: `backup-stale-banner`, `backup-stale-create`, `offsite-backup-{filename}`, `offsite-badge-{filename}`.

## Scheduled Auto-Backup + Auto Safety Backup — DONE & VERIFIED (2026-06)
- **Scheduled auto-backup** (user-configurable): file-based schedule (`schedule.json`) + status (`schedule_state.json`) in ROOFSPAN_BACKUP_DIR so they survive DB restores. In-process asyncio scheduler (`services/backup.scheduler_loop`, started in server.py startup) ticks every 60s; runs a full backup once/day at the chosen local HH:MM (catch-up if the app was off at that minute). Status persists as OK/FAIL and stays FAIL until a successful run. Endpoints: `GET/PUT /api/admin/backups/schedule`, `POST /api/admin/backups/schedule/run-now` (retry a failed one). UI (`backup-schedule-card`): On/Off Switch, daily time input, Save, Run now, and a green "succeeded"/red "FAILED (…error… please Run now until it succeeds)" status. Verified: scheduler fired within ~60s → OK; run-now → OK; invalid time → 400; Sales → 403.
- **Auto Safety Backup before restore**: restore now first creates `roofspan_<TS>_safety.dump` (via `create_backup(suffix="_safety")`); if the safety backup fails the restore is ABORTED (user never loses an undo point). Response returns `safety_backup`. The safety file lives on the persistent volume (not in the DB) so it survives the restore and is itself restorable to undo. Verified: restore returns safety_backup filename; file appears in the list.
- Note: scheduled backups are local-only (no auto off-site); users can Copy off-site per file.

## Auto Off-site for Scheduled Backups — DONE & VERIFIED (2026-06)
- Added `offsite` flag to the backup schedule config. When enabled, `run_scheduled_backup()` copies each successful daily/auto backup off-site (via existing `copy_offsite`) and records `offsite_status` OK/FAIL + `offsite_error` in schedule_state.json (separate from the local `last_status`). `ScheduleIn.offsite` + `set_schedule(..., offsite)`.
- UI: "Also copy each automatic backup off-site" Switch (`schedule-offsite-switch`) in the Automatic backups card; status box shows a green "Off-site copy succeeded" or amber "Off-site copy failed: …" line (`schedule-offsite-status`).
- Verified: enabling offsite + Run now → local OK + offsite OK, newest backup shows offsite=true in list and "Off-site" badge in UI.

## Dashboard Backup-Health Badge — DONE & VERIFIED (2026-06)
- New `GET /api/admin/backups/health` (SENSITIVE_ROLES) returns a compact summary: `level` (ok/warn/error) + `label`, newest-backup age, count, scheduled + off-site status. Logic: no backups or scheduled FAIL → error; stale (>7d) or scheduled off-site FAIL → warn; else ok ("Backed up today"/"Backed up Nd ago").
- Dashboard (`Dashboard.jsx`) shows a small color-coded pill badge in the header (owner/admin only, `dashboard-backup-badge`) that links to /admin/backups. Verified: green "Backed up today" pill renders; endpoint returns ok; Sales → 403. NOTE: Dashboard route is `/` (not `/dashboard`).

## Canvass Sections / Sales Area Assignment — COMPLETE & VERIFIED (2026-06)
Additive extension (does NOT change Territory/RentCast). Territory → Imported Properties → Canvass Sections → Assigned Rep → Mobile.
- DB migration a1c2e3d4f5b6 (down_revision f7a8b9c0d1e2): tables canvass_sections (FK territory_id CASCADE, assigned_user_id SET NULL, geometry JSONB, color, active, indexes) + canvass_section_properties (FK section/property CASCADE, unique(section_id,property_id), indexes). Upgrade+downgrade verified.
- Backend new: routers/canvass.py, services/canvass.py, schemas_canvass.py, geo.py helpers (is_valid_polygon, polygon_fully_contained, unique_ring_points). Endpoints: GET/POST/GET/PUT/DELETE /api/canvass-sections (+ filters territory_id/assigned_user_id/active), POST /preview, GET /{id}/properties. Mobile: GET /api/mobile/canvass-sections, GET /api/mobile/canvass-sections/{id}/properties (sales see ONLY own active sections; 403 on others — server-authoritative).
- Decisions: overlap = BLOCK save (409, preview lists conflicts w/ address+owning section+rep); containment = ALL vertices inside Territory (422 otherwise); polygon >=3 unique pts. RBAC: MANAGE_ROLES (owner/administrator/office) write; sales blocked. Audit: canvass_section.create/update/delete/assign. Territory delete cascades sections+membership; Properties/Visits/Leads preserved.
- Office MapView.jsx (additive): Canvass Sections sidebar + empty state, Draw Canvass Section (distinct from Draw territory), preview dialog (counts+conflicts), color+rep assign, section GeoJSON layers (canvass-section-fill/line), select→fit+filter to members (existing filters still apply via sectionPropIds), reassign/delete. WebView2 DOM-marker pins preserved.
- Mobile MapScreen.js rewritten to assignment-driven "My Area" (only assigned sections+properties, polygon render, DNK red preserved, offline cache canvass_sections + canvass_props_{id}, empty/offline states). mobile/src/canvass.js pure helpers + tests.
- Tests: backend tests/test_canvass_sections.py (9 passed); mobile canvass.node.test.js (passed). Full serial backend suite: 525 passed / 4 failed (all pre-existing & unrelated: 3 brittle source-inspection tests on untouched PropertySheet/imports/integrations; 1 inventory test that passes in isolation) / 43 skipped. test_maptiler_geocoding pre-existing broken import (missing mapbox_vector_tile). NO canvass regressions.

## Git Sync + Backup Upload Storage Fix — DONE & VERIFIED (2026-06)
- Pulled user's remote changes: merged `roofspan/main` (4 commits: Expo SDK 54 photo file read fix, Relay-safe photo size validation, Relay photo transport regression tests) with local unpushed commit (keepalive heartbeat + sync status chip). Clean auto-merge, no conflicts. Verified: all mobile node tests pass (canvass, mapconfig, pairing, photo, photo_transport_contract, refresh, scope, sync, transport); Office web app renders.
- Resolved blocking `ephemeral-upload-storage` lint on `backup.py` save_upload (uploaded DB-dump import). Root cause: it was the only spot writing uploaded bytes to local disk with no storage abstraction (unlike photos' `object_storage.put_object`). Fix: added `object_storage.put_upload(path, data, local_base=...)` dual-mode helper (self-hosted -> atomic local write into BACKUP_DIR; hosted -> Emergent managed object store), and `save_upload` now delegates to it. Self-hosted behavior fully preserved (dump lands in BACKUP_DIR, appears in list/download/restore). Verified: save_upload writes to BACKUP_DIR, atomic .partial cleanup, appears in list_backups, resolve_path ok, non-pg files rejected; backend starts clean.

## Inspection Field Parity (Office ↔ Mobile) — DONE & VERIFIED (2026-06)
- Goal: same inspection details captured AND displayed in both Office (web) and Field (mobile).
- Backend already unified (InspectionIn/Out + MobileInspectionIn share: inspector, roof_condition, findings, recommended_work, measurements, notes, inspection_date). Divergence was UI-only.
- Mobile (`mobile/src/screens/Inspection.js`): added Inspector field (prefilled from useAuth user.full_name/email); roof_condition + inspector now single-line. Full set: inspector, roof_condition, findings, recommended_work, measurements, notes (+ photos).
- Office (`frontend/src/pages/LeadDetail.jsx`): added Measurements + Notes inputs to the Record-inspection dialog (`insp` state now includes measurements); display card now shows Findings, Measurements, Notes (were hidden) + inspector (falls back to created_by) + date.
- Backend (`backend/routers/mobile.py`): mobile create_inspection auto-sets inspection_date when absent; `_insp_out` now returns inspection_date for parity.
- Test: updated `mobile/src/tests/inspection_focus_contract.node.test.js` (5→6 fields). Verified: mobile-endpoint inspection with all fields reads back identically via Office `/api/inspections`; Office lead page renders all fields (screenshot); mobile node tests pass; frontend compiles.

## Roof Measurement System — INCREMENT A: DONE & VERIFIED (2026-06)
Locked product decisions (user): snapshot-revision model; each revision an immutable snapshot once verified/locked; edits clone a NEW revision that supersedes; totals DERIVED not entered; waste is NOT stored (estimating = Increment B); status draft->field_complete->office_verified->locked + return-to-field; Field/Sales create/edit+Field Complete, Office/Owner/Admin verify/lock/return; pitch stored as decimal rise over fixed run 12; linear=decimal feet, area=sq ft (feet/inches is UI-only); edges stored as individual segments; stable facet labels.

Chain: Property -> Inspection -> MeasurementSet -> MeasurementRevision(n) -> Structures / Facets / Edges / Penetrations / Summary.

Backend (all tested, 9/9 pytest + main-agent curl):
- models.py: 7 tables (measurement_sets, measurement_revisions, measurement_structures, measurement_facets, measurement_edges, measurement_penetrations, measurement_summaries). Migration b7c8d9e0f1a2 (head).
- schemas_measurements.py: whole-document nested in/out with client 'ref' linkage; derived MeasurementTotals.
- services/measurements.py: create_revision, replace_children (draft only), clone_revision (deep copy -> new draft, supersedes), transition_status (state machine + roles), build_out (derives total area/squares/area-by-pitch/area-by-structure/edge LF totals/penetration counts/reported-delta), list_revisions_for_set.
- routers/measurements.py (Office /api/measurements): GET list, GET {id}, POST, PUT, POST {id}/status, POST {id}/new-revision, DELETE (draft only). Locked PUT/DELETE -> 409.
- routers/mobile.py (/api/mobile/measurements): POST (idempotent), PUT (If-Match), POST {id}/field-complete, GET list, GET {id}; sales scoped to own lead/property.

Frontend:
- Office: components/MeasurementWorksheet.jsx embedded in LeadDetail 'Roof measurements' section (section-measurements). Revision selector + history, status badge + workflow buttons, live totals, editable Structures/Facets/Edges/Penetrations tables + Summary/conditions; read-only when locked; New revision to edit a locked one.
- Mobile: src/screens/Measurements.js (touch-first: structure/facet add, pitch chips, ft/in edge entry, penetration +/- counters, live totals, offline save via durable queue, Save & Mark Field Complete). Registered in App.js (Leads + Map stacks); opened from Inspection screen button. Code-verified (RN not browser-testable); mobile API tested.

Regression suite: backend/tests/test_measurements_pytest.py, backend/tests/test_measurements_lifecycle.py.

NEXT: Increment B (Takeoff -> Estimate): estimates select a measurement revision; company Takeoff Templates map metrics to existing Assemblies/line items; waste as estimating assumption (company default 10%, per-template/assembly default, estimate + per-structure override); drip edge computed in takeoff (eave+rake, override). Increment C: soft validation warnings + 'measurements changed since Estimate #X' recalculation prompts + auto-immutability when a revision is referenced by an accepted quote/job.

## Increment A.1 — Measurement Photos: DONE & VERIFIED (2026-06)
- Photos attach to measurement records by stable IDs via existing durable/offline photo pipeline. record_types added: measurement_revision, measurement_structure, measurement_facet, measurement_penetration (allowlist in mobile.py upload_photo).
- Backend (all tested, tests/test_measurement_photos.py, 6/6): upload to any of the 4 levels; new GET /api/mobile/photos/measurement/{revision_id} aggregate ('All measurement photos'); new DELETE /api/mobile/photos/{id}; locked/immutable revision blocks BOTH upload and delete of its photos (409); clone_revision now deep-copies + remaps photo attachments to the new revision/structure/facet/penetration ids (services/measurements.py _copy_photos + resolve_revision_for_photo + revision_photo_records). mobile_authz.assert_record_access resolves measurement_* to the set's lead/property for sales scoping.
- Office worksheet (MeasurementWorksheet.jsx): compact thumbnails beside each saved facet & penetration (hideWhenEmpty) + 'All measurement photos' card (PhotoGallery now accepts sourceUrl/sourceParams).
- Mobile (Measurements.js): PhotoSection for general revision photos + per saved facet (offline capture via existing queue); prompts to save first before attaching. RN not browser-tested; endpoints API-tested.
- Increment A is now fully complete (original locked scope closed). NEXT: Increment B (Takeoff->Estimate) with VERSIONED Takeoff Templates (Estimate binds Measurement Revision N + Takeoff Template Revision M), then Increment C.

## Roof Sketch + Aerial Import — IN PROGRESS (branch feature/roof-sketch-import, 2026-06)
Executing approved Plan 1 (roof sketch) then Plan 2 (imports) in order, TDD, committing green milestones.
DONE & GREEN (Plan 1):
- Task 1 shared geometry core `packages/roof-sketch-core` (distance, polygonArea shoelace, pitchAdjustedArea, calibrateScale, createSketchDocument/normalize, findSharedEdges, validateSketch [zero-length/self-intersection/dangling/open-loop + gap warning], deriveProposals [unresolved-scale suppresses dimensional proposals; locked edge => discrepancy not overwrite], compareProposal). 26/26 node assertions.
- Task 2 versioned persistence: `measurement_sketch_documents` (migration e0f1a2b3c4d5, down_revision d9e0f1a2b3c4; single head). Service `measurement_sketches.py`: get/list/save (structure-level optimistic concurrency; SketchConflict carries server doc), locked-revision rejection, clone_sketches remaps to new structure ids w/ version reset. Hooked into measurements.clone_revision. Service test green.
- Task 3 APIs: Office `routers/measurement_sketches.py` (GET list/one, PUT with 409 conflict payload {message,server}); Field mirror in mobile.py under /api/mobile/measurements/{rev}/sketches/{structure} using _assert_measurement_scope. Registered in server.py. API test green (create v1, update v2, stale 409, independent per-structure, field mirror, locked 409).
- Task 5 offline sync foundation: `mobile/src/sketchCache.js` (sketchDetailKey/sketchDraftKey/sketchUpdateMutationId `measurement-sketch-update:<rev>:<structure>`, makeSketchDraft keeps local doc+version token+base server doc). queue.js identity extended for kind measurement_sketch_update (coalesces repeated same-structure edits; existing measurement/photo identities unchanged). cache.js read-through cache.sketch + save/load/clear sketch draft. 15/15 node assertions; measurement_cache + sync regressions green.
REMAINING: Task 4 (Office SVG editor UI), Task 6 (Field RN SVG touch editor UI), Task 7 (CI workflow), then ENTIRE Plan 2 (EagleView/HOVER/GAF + generic PDF/XML/JSON/CSV/DXF/ESX import, confidence scoring, reconciliation UI + 2D overlay, provenance, duplicate SHA-256, import-artifact backup/restore). Not started; not claimed complete.
Verification (green now): geometry core 26/26; sketch service; sketch API; measurement pytest 9/9; measurement photos; mobile sketch_cache 15/15 + measurement_cache; alembic single head e0f1a2b3c4d5.

## Roof Sketch FOUNDATION CORRECTIONS — partial (branch fix/roof-sketch-foundation, 2026-06)
Base: feature/roof-sketch-import (sketch commits are NOT on remote main yet — need Save to Github).
FIXED & GREEN (commit b859ea1):
- CRITICAL 1 atomic concurrency: save_sketch now uses PostgreSQL compare-and-swap (UPDATE ... WHERE document_version=:expected RETURNING). 0 rows -> reload + SketchConflict. No last-write-wins. Pytest proves two same-version writers => one wins, other 409.
- CRITICAL 2 canonical normalization: _normalize_document reconciles embedded document.{structure_id,edit_mode,schema_version} with authoritative route/DB values (route structure id wins); rejects contradictions + unsupported mode/schema (422). Tested.
- CRITICAL 3 clone id remapping: clone_sketches now takes structure/facet/penetration maps and remaps document.structure_id + proposal_decisions target ids + relational-id fields; graph client ids left stable. Tested (no old structure id remains in cloned doc).
- IMPORTANT 6 salesperson scope on Office sketch routes: routers/measurement_sketches.py `_scope()` reuses mobile_authz (lead/property) for sales; owner/office broader. (Code done; dedicated two-rep A/B denial test still TODO.)
- IMPORTANT 7 real pytest: both sketch test files converted to pytest (test_* fns), safe teardown deletes ONLY the set the test created, no destructive whole-property delete.
- SECURITY: removed hardcoded owner creds from api test (now env-gated RS_TEST_EMAIL/PW, skips without). NOTE: RoofSpan#Owner2026 was committed earlier at 4b01716 (real active owner acct) -> MUST BE ROTATED.
- Verified: sketch service pytest 1 passed; sketch api 1 skipped(no creds)/1 passed(with env); geometry core 26/26; measurement pytest 9/9; measurement photos; mobile sketch_cache 15/15; single alembic head e0f1a2b3c4d5.
STILL OUTSTANDING (must finish before Plan 2 / editors): IMPORTANT 4 edge-loop connected-graph topology validation; IMPORTANT 5 real gap/overlap/disconnected-component/duplicate/floating-facet detection (+ geometry tests); two-rep salesperson A/B API denial test; IMPORTANT 8 Field deps (@roofspan/roof-sketch-core file: dep + react-native-svg 15.12.1 in mobile/package.json + lockfile + Metro resolve); IMPORTANT 9 CI workflow roof-takeoff-contract.yml sketch coverage.

## LEARNING — Save-to-GitHub only publishes FILE-TOOL edits (2026-06)
Emergent "Save to GitHub" commits ONLY files changed via the agent's file-editing tools
(create_file/search_replace), NOT files modified by shell side-effects (e.g. `yarn install`
regenerating `frontend/yarn.lock`). Such shell-generated changes show as tracked+modified in git but
are skipped by Save. FIX: apply the needed change to the generated file via `search_replace` (byte-
identical to the tool's output). Confirmed with support@emergent.sh. This is why the corrected
`frontend/yarn.lock` (adding `@roofspan/roof-sketch-core@file:` entry) repeatedly failed to publish
until re-applied via search_replace (blob 1d4e4c1, replacing broken 2d6b580).
