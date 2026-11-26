# RoofSpan Roadmap

## Accepted test-suite baseline (2026-06)
1,209 tests: 1,152 passed, 0 failed, 0 errors, 56 skipped, 1 xfailed. The user accepted this baseline.
The 356 legacy TEST_ customers and everything linked to them are KEPT on purpose (decision 2026-06). Do not delete them without new approval.

## Technical backlog (separate items)
- **TB-1 Isolated test database**: run automated tests against a separate disposable PostgreSQL database, never the working DB.
- **TB-2 Overlapping-run protection**: add a run lock so two suites can't run at once, and make cleanup skip records created by a different run.
- **TB-3 Stripe test credentials**: replace the expired Stripe sandbox key, then verify the subscription lifecycle and seat billing (tests/test_stripe_billing.py is currently skipped).
- **TB-4 Document the expected failure**: tests/test_round3_fixes_iter121.py::test_probe_no_ids_insert_at_front_reapply is a known-limitation probe (xfail): clients that save takeoff lines without line IDs are matched by position only. The server now refuses id-less saves when takeoff lines exist, so the probe can't pass by design. Decide whether to keep it as an xfail or rewrite it to assert the refusal.
- **TB-5 Gated integration tests before production release**: before release, verify the 45 gated suites (relay, Valkey, live ABC Supply, live Control Plane PostgreSQL, live Office smoke) in a real integration environment.

- **TB-6 Test transport through the public preview URL**: intermittent 6-40s TCP connect stalls at the preview CDN edge cause rare
  ConnectTimeoutError in any API test (seen in test_licensing_api). Run the suite against the internal backend URL / isolated env (pairs with TB-1).
- **TB-7 Mobile node integration tests**: refresh.node.test.js / sync.node.test.js write to the live Office DB; gated, run only inside manual_begin/manual_end.

## Proposed enhancements (future consideration — NOT approved for build)
- **One-tap call / text from Field My Day** (and log that contact automatically).
- **Attempted vs completed contact** in contact logging (e.g. "Called — no answer" vs "Spoke with homeowner").
- **Lost reason** captured when a lead is marked Lost.

## Product rounds (KISS redesign — COMPLETE, feature freeze from 2026-06)
All accepted by the owner:
1. Simplified seven-area navigation.
2. Settings hub for administrative configuration.
3. Dynamic five-stage Lead workflow.
4. Simplified Estimate / Takeoff and Materials workflows.
5. Jobs: Job Manager + managed Crews, scheduling with the RoofSpan date-range calendar, automatic Ready to install, full-width Job materials.
6. Job closeout: Job Manager type-ahead, sales cannot see purchasing costs, confirmed test jobs/users cleaned up.
7. Test-suite stabilisation and test-data leak prevention; Field lead-assignment validation.
8. Sales follow-up and reminders: several follow-ups per lead, contact history, booked inspections, proposal attention,
   Office Home + Field My Day, one status list (New/Contacted/Qualified/Won/Lost), offline sync + conflicts,
   Won/Lost auto-cancel, 122-lead status correction, Office calendar date/time picker.

## Release candidate (feature freeze) — production-readiness items
Done in the preview environment (2026-06):
- Full backend suite, Office production build, Field compile/config/API compatibility check, Windows packaging test suite,
  and an upgrade rehearsal on a copy of the working database (pre-redesign schema -> head) all completed. See PRD.md.
- Upgrade migration b1f0c2d3e4a5 now maps Converted -> Won only with an accepted proposal, otherwise Contacted
  (the same rule as the approved preview correction), so customer upgrades don't need the one-off script.

Outstanding before production:
- **RC-1 Physical Android + iOS acceptance** (owner) — memory/FIELD_FOLLOWUP_DEVICE_CHECKLIST.md. NOT yet performed.
- **RC-2 Installed Windows Office build + upgrade test** (owner, outside preview): fresh install AND upgrade of an existing install
  (upgrade coordinator `--migrate` runs Alembic to b1f0c2d3e4a5). The Windows-only installer/service tests (105) were skipped on Linux.
- **RC-3 Version number**: windows/VERSION is still 0.4.8 and app.json 1.0.0; set the release-candidate version before building.
- **RC-4 Expo SDK patch drift**: `expo install --check` lists 10 packages one patch behind (expo 57.0.20 vs ~57.0.34, etc.).
  Not a build blocker; decide whether to align before the RC build (would need a full device retest).
- **RC-5 Field UI test dependency**: src/tests/roof_preview_ui.node.test.js needs `react-test-renderer` (not installed) — the test
  cannot run here. Not an app dependency.
- **RC-6 Office bundle size**: main JS 643 kB (CRA warning). Not a blocker.
- MOCKED integrations still MOCKED: **proposal / acceptance email** and **ABC Supply**. Stripe sandbox key expired (TB-3).
- TB-1 … TB-7 above; TB-5 (gated integration suites) must be done before production.
