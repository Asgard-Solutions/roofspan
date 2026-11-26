# RoofSpan release candidate — Office 0.5.0 / Field 1.1.0 (prerelease, channel "dev")

Status: ready to build for acceptance testing. NOT yet done: Windows install + upgrade test, Android and iOS acceptance
(FIELD_FOLLOWUP_DEVICE_CHECKLIST.md), hosted Control Plane deployment (CONTROL_PLANE_DEPLOYMENT_RC.md, awaiting approval).
Proposal email and ABC Supply remain MOCKED.

## Versions (authoritative sources)
| Component | Version | Source |
|---|---|---|
| RoofSpan Office (backend `/api/version`) | 0.5.0 (shown "0.5.0-dev") | `windows/VERSION` via `windows/version.py`, `backend/version.py` |
| Windows installer (MSI ProductVersion + Burn setup.exe) | 0.5.0 | `windows/VERSION` (build.ps1 `$canonicalVersion`) |
| Upgrade executable + 4 services (backend, relay connector, update service, update broker) | 0.5.0 + Git SHA | `windows/VERSION` embedded by `winbuild/build_exes.ps1` (`--build-info`) |
| Office frontend | 0.5.0 + Git SHA | `frontend/roofspan-build.json` written by `installer/build-office-frontend.js`; build.ps1 refuses a mismatch |
| RoofSpan Field Android / iOS | 1.1.0 | `mobile/app.json` `expo.version` (also `mobile/package.json`) |
| Android versionCode / iOS buildNumber | EAS remote counter | `mobile/eas.json` `appVersionSource: remote`; `preview` and `production` profiles `autoIncrement: true` |
| Relay protocol | 1 (unchanged) | `ROOFSPAN_PROTOCOL_VERSION` default |
| Office DB head | `c7e2a9b4d1f3` | `backend/alembic/versions` |
| Control Plane DB head | `f3a9c1d2b7e4` | `backend/control_plane/alembic/versions` |
| Minimum Field accepted by Office | 1.1.0 | `licensing/config.py` `MIN_MOBILE_VERSION` (env `ROOFSPAN_MIN_MOBILE_VERSION`) |
| Minimum Office accepted by Field | 0.5.0 | `mobile/src/compat.js` `MIN_OFFICE_VERSION` |

Prerelease: the installed Office stays on channel "dev" (`ROOFSPAN_CHANNEL` unset). Set `stable` only after acceptance.

## Supported installation and upgrade sequence
1. Control Plane (when approved): CONTROL_PLANE_DEPLOYMENT_RC.md. Office 0.5.0 also works against today's Control Plane;
   only "Restore my company" and recovery codes need the new one.
2. Ask reps to open Field and let it sync. Not required (nothing is deleted), but it keeps the upgrade simple.
3. Office:
   - New computer: run `RoofSpanSetup-0.5.0.exe` (Burn bundle; includes `RoofSpanOffice-0.5.0.msi`), then complete first-run setup (company, owner account).
   - Existing Office 0.4.8: run the same setup on that computer. The upgrade coordinator takes a backup of the database and test-restores it to verify it, keeps
     `ProgramData\RoofSpan` (config `roofspan.env`, `identity\` installation key, photos `images\`) and runs migrations
     b1f0c2d3e4a5 + c7e2a9b4d1f3; on failure it restores the backup and the previous version. Because the installation
     identity is kept, the Control Plane installation, licence, subscription and every Field pairing stay the same.
     Check the log line `[c7e2a9b4d1f3] Won->Contacted corrected: N; left unchanged for manual review: M`.
4. Field on every phone: install 1.1.0 OVER the existing app (Android: same package `io.roofspan.field` and the same EAS
   signing key, higher versionCode; iOS: same bundle ID, higher buildNumber via TestFlight/ad hoc). Never uninstall.
   - Pairing (device credential + installation binding) is in the phone's secure storage and the offline queue/cache in
     the app's SQLite database (`roofspan.db`); an in-place update keeps both, so no re-pairing or sign-in is needed.
   - Pending offline changes keep their idempotency keys and are replayed once by 1.1.0 (legacy "Interested" → "Qualified").
   - Until a phone is updated, Office 0.5.0 rejects Field 1.0.0 (426); 1.0.0 keeps its queued work (marked failed, never
     deleted) and 1.1.0 sends it after the update.
   - A phone updated before its Office shows "RoofSpan Office needs an update" and holds its work until Office is 0.5.0.

## Compatibility matrix (tested 2026-11-26 against real servers: current source and the 0.4.8 source)
| Office | Field | Result |
|---|---|---|
| 0.4.8 | 1.0.0 | works as before |
| 0.5.0 | 1.1.0 | works |
| 0.5.0 | 1.0.0 | Office answers 426 "Update RoofSpan Field to version 1.1.0 or newer…" to every Field data request; no write happens |
| 0.4.8 | 1.1.0 | Field blocks itself: "RoofSpan Office needs an update" (shows both versions); nothing is sent |
| Field 1.0.0 → 1.1.0 with pending offline changes | | kept (1.0.0 marks them failed, never deletes), replayed once by 1.1.0 |
Reproduce: `scripts/rc_compat_matrix.js` (needs a second Office from the 0.4.8 source on another port).
Mechanism: Field sends `X-RoofSpan-App-Version`; the Office relay tunnel tags device traffic
`X-RoofSpan-Relay-Forwarded`, so relayed requests without a version are Field 1.0.x. Office web calls aren't relayed.

## Corrective migration c7e2a9b4d1f3
Corrects Won -> Contacted only with positive evidence: legacy conversion audit (`customer.from_lead`), customer link, no
proposal ever accepted, no job for the lead's customer/proposals, no audited manual status edit since conversion, not
corrected before. Everything else that is Won without an accepted proposal is left unchanged and gets one
`lead.status_review_needed` audit entry (Audit log) with the reasons. Every correction writes `lead.status_correction`.
No deletions; re-running changes nothing.
| Rehearsal (copy of working DB) | Result |
|---|---|
| A: from before the original status migration | 0 corrected, 0 flagged; Won 149 (accepted proposals), legacy statuses 0 |
| B: after the original incorrect migration (122 wrongly Won) + 3 simulated user edits | 112 corrected, 9 flagged for review (2 user status edits, 7 whose customer has a job), lead moved to Qualified untouched, 149 legit Won kept, re-run 0/0 |
| C: already-corrected DB (preview working DB) | 0 corrected, 0 flagged, no row changes |
The earlier rehearsal estimate (119 + 2) used a looser rule; the stricter evidence moves 7 of the 119 to manual review.
Scripts: `scripts/upgrade_rehearsal.sh` (A), `scripts/upgrade_rehearsal_incorrect.sh` (B), `scripts/upgrade_rehearsal_corrected.sh` (C).

## Build requirements
- Source: commit `f5632fb6c63b64439b8029c8c6ac157ef21ae77b` contains every application change (later commits only touch
  `memory/` and `test_reports/`; verify with `git diff --stat f5632fb HEAD -- . ':!memory' ':!test_reports'` → empty).
  Note: the platform auto-save does not commit `package-lock.json`; it was committed explicitly in f5632fb.
- Office (Windows): `windows/installer/stage.ps1` then `build.ps1` from a Git checkout of that commit (Node/yarn, .NET SDK,
  Python/PyInstaller, WiX). The guarded frontend build sets aside `frontend/.env*` and `REACT_APP_*`, builds with relative
  `/api`, strips preview-only scripts, stamps version + SHA and rejects preview/hosted addresses (PowerShell 5.1 and 7.x).
- Field: `cd mobile && eas build --profile preview --platform all`; EAS runs `npm ci` against the root `package-lock.json`.
  Expo SDK 57 (`expo` 57.0.20), React Native 0.86.3, React 19.2.3 (unchanged from package.json). Regenerating the lock
  re-resolved packages within their existing package.json ranges: Expo modules moved up patch releases inside SDK 57
  (e.g. expo-constants 57.0.25, expo-image-picker 57.0.22, expo-sqlite 57.0.7, expo-dev-client 57.0.22,
  @expo/metro-runtime 57.0.19, expo-splash-screen 57.0.12); `expo install --check` now reports only `expo` itself
  (57.0.20, expected ~57.0.34). The previous lock (Expo 54) was never installable, so there is no older locked runtime to
  compare with. Device acceptance covers these builds.
