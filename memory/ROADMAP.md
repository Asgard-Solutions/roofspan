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

## Product rounds
- DONE 2026-06: Sales follow-up and reminders (see PRD). Next: user acceptance + device check of Field My Day.
