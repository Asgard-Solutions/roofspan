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

## Supported upgrade sequence
1. (When approved) deploy the hosted Control Plane from the same commit — CONTROL_PLANE_DEPLOYMENT_RC.md.
   Office 0.5.0 still works against today's Control Plane; only "Restore my company"/recovery codes need the new one.
2. Ask reps to open Field and let it sync (pending work is never deleted, but syncing first is cleanest).
3. Upgrade RoofSpan Office to 0.5.0 (runs migrations b1f0c2d3e4a5 + c7e2a9b4d1f3; check the upgrade log line
   `[c7e2a9b4d1f3] Won->Contacted corrected: N; left unchanged for manual review: M`).
4. Update RoofSpan Field to 1.1.0 on every phone by installing over the existing app (never uninstall: that deletes
   the pairing and any unsynced work). Field 1.0.0 is rejected by Office 0.5.0 until updated; its queued changes stay
   on the phone and sync after the update (legacy "Interested" becomes "Qualified").
- Field 1.1.0 against an Office still on 0.4.8 shows "RoofSpan Office needs an update" and doesn't sync.

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
- Office (Windows): `windows/installer/stage.ps1` then `build.ps1` from a Git checkout of the RC commit, with Node/yarn,
  .NET SDK, Python/PyInstaller and WiX. The frontend is built by `build-office-frontend.js`: it sets aside any
  `frontend/.env*` and `REACT_APP_*` variables, builds with relative `/api`, strips preview-only scripts from
  index.html, stamps version + SHA, and rejects output containing a preview/hosted address. Works on PowerShell 5.1 and 7.x.
- Field: `cd mobile && eas build --profile preview --platform all` (internal test builds; build numbers auto-increment
  from the EAS remote counter; existing numbers are not reset). Install over the existing app. The root
  `package-lock.json` was out of sync with `mobile/package.json` (Expo 54 vs 57) so `npm ci` on EAS would have failed;
  it is regenerated (Expo 57.0.20 / RN 0.86.3 / React 19.2.3 unchanged).
- Same source revision for Office, Field and the Control Plane deployment.
