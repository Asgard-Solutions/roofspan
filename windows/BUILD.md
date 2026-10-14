# RoofSpan Windows Build - Canonical Procedure

This is the ONE canonical clean-build procedure. There is no alternate/Emergent-only workflow, and you
do NOT need to activate `.venv`, manually run `pip`/`yarn`, or change PowerShell encoding.

## Prerequisites (one-time, on the Windows build host)
- Windows 10/11 x64, Visual Studio 2022 Developer PowerShell (or plain PowerShell 5.1 / 7).
- WiX Toolset v5.0.2: `dotnet tool install --global wix --version 5.0.2`
  (build.ps1 auto-restores the required CLI extensions pinned to 5.0.2:
  `WixToolset.BootstrapperApplications.wixext`, `WixToolset.Util.wixext`, `WixToolset.Firewall.wixext`.
  Note: WiX 5 renamed `WixToolset.Bal.wixext` -> `WixToolset.BootstrapperApplications.wixext` for CLI use.)
- Node.js LTS + Yarn (`corepack enable`).
- Repo virtualenv with PyInstaller + backend deps + pywin32 (created once):
  ```powershell
  cd D:\AsgardSolutions\RoofSpan
  py -m venv .venv
  .\.venv\Scripts\pip install -r backend\requirements.txt pyinstaller pywin32
  ```
  The build scripts automatically use `.\.venv\Scripts\pyinstaller.exe` - do NOT activate `.venv`.
  build_exes.ps1 also auto-installs pywin32 into that env if missing (the three services are real
  pywin32-hosted Windows SCM services, built ONEDIR: services\<name>\<name>.exe + \_internal\).
- Prerequisite installers (not committed). Both are embedded into RoofSpanSetup.exe so the customer never
  downloads anything at install time:
  - PostgreSQL (EDB silent installer): `D:\AsgardSolutions\Prerequisites\PostgreSQL\postgresql-16.14-2-windows-x64.exe`
  - WebView2 (FULL Evergreen Standalone x64 installer, NOT the download bootstrapper):
    `D:\AsgardSolutions\Prerequisites\WebView2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe`
    Download it from https://developer.microsoft.com/microsoft-edge/webview2/ → "Evergreen Standalone
    Installer" → x64 (stable permalink: https://go.microsoft.com/fwlink/?linkid=2124701). The small
    `MicrosoftEdgeWebview2Setup.exe` download bootstrapper is NOT accepted (it needs internet at install).

## Canonical clean build
```powershell
cd D:\AsgardSolutions\RoofSpan

git checkout main
git pull --ff-only origin main
git status
git rev-parse HEAD

Remove-Item -Recurse -Force D:\AsgardSolutions\RoofSpan\_stage -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force D:\AsgardSolutions\RoofSpan\windows\installer\dist -ErrorAction SilentlyContinue

cd D:\AsgardSolutions\RoofSpan\windows\installer

.\stage.ps1 -StageDir ..\..\_stage

$Version = (Get-Content ..\VERSION -Raw).Trim()

.\build.ps1 `
  -Version $Version `
  -StageDir ..\..\_stage `
  -PostgresInstaller "D:\AsgardSolutions\Prerequisites\PostgreSQL\postgresql-16.14-2-windows-x64.exe" `
  -WebView2StandaloneInstaller "D:\AsgardSolutions\Prerequisites\WebView2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
```

`build.ps1` rejects a `-Version` that does not equal `windows\VERSION`. Change the checked-in version
first; do not produce multiple customer builds with the same version or manually override release identity.

## Verify artifacts
```powershell
Get-Item `
  ".\dist\RoofSpanOffice-$Version.msi", `
  ".\dist\RoofSpanSetup-$Version.exe", `
  ".\dist\RoofSpanSetup.exe" |
Select-Object FullName,LastWriteTime,Length
```

## What the scripts do for you (deterministic)
- `stage.ps1`
  - Fails fast if `yarn`, `frontend/package.json`, or `frontend/yarn.lock` are missing.
  - Builds the three service EXEs via `build_exes.ps1`.
  - ALWAYS runs `yarn install --frozen-lockfile` (syncs deps after any `git pull`) then `yarn build`.
- `build_exes.ps1`
  - Uses repo-local `.\.venv\Scripts\pyinstaller.exe` if present, else falls back to PATH `pyinstaller`,
    else fails with an actionable message. No `.venv` activation required.
  - Fails fast if `backend\alembic` or `backend\alembic.ini` are missing (packaged by the spec).
  - Embeds the exact Git SHA and `windows\VERSION` into the backend and Relay connector.
  - Executes the frozen Relay connector with `--build-info` before and after staging. The build stops if
    the binary does not contain the hosted installation-id v2 contract, canonical identity endpoint, and
    canonical `/api/relay/installation` route.
- `build.ps1`
  - Requires `-StageDir`, `-PostgresInstaller`, `-WebView2StandaloneInstaller`; validates WiX, the full
    staged payload, and both prerequisite installers before building.
  - Re-runs the Relay connector build-info probe and refuses an old `_stage`, a mismatched source SHA, or
    a version that differs from `windows\VERSION`.
  - Builds into a clean isolated folder and checks native exit codes after MSI + bundle compile and after
    signing, so a failed rebuild can never publish or copy an older installer as the new output. The
    stable `RoofSpanSetup.exe` is refreshed only on full success, and the build prints the release
    version, artifact size, and SHA-256 so the exact file under test is identifiable.
  - Produces the MSI, the versioned `RoofSpanSetup-<ver>.exe` Burn bundle, and `RoofSpanSetup.exe`.
- Installer chain (`bundle.wxs`): every package is PerMachine (double-click elevates via UAC). WebView2
  Evergreen Standalone (skipped if already installed) -> PostgreSQL prep + validation -> EDB PostgreSQL
  (skipped whenever the RoofSpanPostgreSQL service exists) -> option-file cleanup -> mandatory database
  authentication/version check -> Office MSI. Service detection only schedules EDB; it does not bypass
  the health check. Both prerequisites are `Permanent` and retained on RoofSpan uninstall.

## Upgrading an existing database without pg_super.bin
Starting with 0.4.7, the installer can validate an older installation using its existing application
credential in `C:\ProgramData\RoofSpan\config\roofspan.env`. It requires the backend's provisioned
`DATABASE_URL=postgresql+asyncpg://roofspan:<password>@127.0.0.1:<local-port>/roofspan` format, successful TCP
authentication, read access to the existing `users` and `leads` tables, and a supported server version.
The verifier uses the saved local port, including legacy non-default ports such as 5442. The check does
not change the password, generate a replacement `pg_super.bin`, or reinstall PostgreSQL.
The backend already supports these legacy installations without a stored superuser credential.

If neither credential is available or authentication fails, setup stops before Office installs. Restore
the matching configuration/identity backup or contact support; do not delete the data directory, remove
the PostgreSQL service, or replace the existing password as an installation workaround. Keep a current
database backup before upgrading. Do not upload `roofspan.env`, `pg_super.bin`, or option files as logs.
Read `C:\ProgramData\RoofSpan\prereq-diag.log` for the sanitized failure reason.

The full-install CI job also builds a test-only higher-version bundle from the production authoring,
removes the disposable runner's superuser secret, rejects an incorrect application password, and checks
that a successful major upgrade preserves a database sentinel, the configuration bytes, and PostgreSQL
start time. This fixture is not a release artifact; consult the CI result for the tested commit.

## Transactional upgrade (roofspan-upgrade.exe)
- **New install:** the bundle installs the MSI as before, and its services start during the install.
- **Upgrade (an older version is installed):** the Burn chain skips the MSI and runs the onefile
  coordinator `roofspan-upgrade.exe`, which runs `msiexec` itself with `ROOFSPAN_COORDINATED=1`. With that
  property the MSI installs files but starts no services and does not launch the shell.
- **States:** `C:\ProgramData\RoofSpan\upgrade\state.json` is replaced atomically and fsynced on every
  change; `journal.log` beside it is append-only.
  - `PREFLIGHT`: checks the PostgreSQL service; takes the `bin` folder from the service image path and
    host/port from `DATABASE_URL` (so 5442 works); logs in with `pg_super.bin` or the app login; detects
    whether the Control Plane is a separate database or the legacy schema; checks free disk space; finds
    and checks the previous full MSI; registers the boot recovery task.
  - `BACKING_UP`: stops the services first, then copies the previous MSI, `roofspan.env` and the identity
    files (with their permissions) and runs `pg_dump -Fc` for each database.
  - `BACKUP_VERIFIED`: checks hashes; replays every archive through `pg_restore` and compares per-table
    row counts; with superuser rights also restores into a scratch database and compares.
  - Then `SERVICES_STOPPED`, `INSTALLING`, `MIGRATING` (`roofspan-backend.exe --migrate --log`, its own exit
    code), `STARTING`, `HEALTH_CHECKING` (PostgreSQL; both migration heads; backend running;
    `/api/health`; `/api/version`; Office UI; licensing log; relay stays running) and `COMPLETE`.
- **Failure:**
  - Before `INSTALLING`: restart the previous services, check they are healthy, end in `ROLLED_BACK`.
  - At or after `INSTALLING`: `RESTORING` removes the new MSI, then restores the databases. With
    superuser rights it restores into a new database, verifies it and swaps names, keeping
    `<db>_failed_<attempt>` (never dropped). Legacy installs (owner only) drop and replay the dumped
    schemas in a single transaction. It then restores the configuration and identity bytes, reinstalls
    the previous MSI, checks the previous version is healthy, and ends in `ROLLED_BACK`. If any of that
    fails, the state is `FAILED` and the verified backup is kept.
- **Interruption:** the boot task and the next setup run call `resume`, which only ever recovers (never
  continues forward). Each attempt has its own backup folder in `upgrade-backups\<attempt>`
  (SYSTEM and Administrators only), and verified backups are never overwritten or auto-deleted. A
  database is restored only from the verified backup of the same attempt.
- **Schema guard:** the Windows backend never migrates an existing database at service start. An
  out-of-date or newer schema refuses to start and points to `RoofSpanSetup.exe`.
- **Missing previous MSI:** if Burn's package cache no longer holds the previous full MSI, run
  `RoofSpanSetup.exe PREVIOUSMSI=<path to RoofSpanOffice-<previous>.msi>`.
- **Fault injection:** exists only in CI test builds (`stage.ps1 -TestFaultInjection`); release
  artifacts must report `fault_injection: false`.

## Build identity and configuration ownership
Each service executable (`roofspan-backend`, `roofspan-relay-connector`, `roofspan-update-service`) embeds
the release version and full Git SHA. Check any of them with `<exe> --build-info`; the output is JSON with
`service`, `version`, `build_sha`, `build_contract` (`roofspan-build-identity-v1`) and `embedded`.
`build_exes.ps1`, `build.ps1` and `Test-InstallerArtifact.ps1` stop when any executable reports a different
version or SHA. Before reusing a saved `roofspan.env`, the backend reconciles it atomically and
idempotently:
- build identity is removed (the executable is authoritative);
- generated secrets, database credentials, customer settings, data paths and unknown keys are preserved
  byte-for-byte;
- missing supported defaults are appended;
- `ROOFSPAN_STATIC_DIR` and `ROOFSPAN_UPDATE_PUBLIC_KEY` are refreshed only when the saved path no
  longer exists and the installed one does.

Only key names are logged.

## Relay connector verification
After installation, this command must report the build SHA used for the installer, the current version,
and contract `hosted-installation-identity-v2`:

```powershell
& "C:\Program Files\RoofSpan Office\services\roofspan-relay-connector\roofspan-relay-connector.exe" --build-info
```

The current connector log starts with `relay: outbound connector loop started` and includes its build SHA.
A log that says only `relay: outbound tunnel loop started -> .../api/relay/tunnel` identifies a pre-v2
connector and must not be accepted as a current customer build.

## CI release gate (build once, test, promote the same bytes)
- **Triggers:** every pull request into `main` runs all seven Windows jobs (there is no path filter, so
  required checks never stay "Expected - waiting"). Pushes run when any packaged input changes:
  `windows/**`, `backend/**`, `frontend/**`, `packages/roof-sketch-core/**`, root `package.json` /
  `package-lock.json`, and the workflow files. `windows/tests/test_release_gate.py` enforces this.
- **Single build:** `clean-machine-full-install` is the ONLY place the release installer is built
  (`stage.ps1` + `build.ps1`). It then runs `installer/Test-InstallerArtifact.ps1`, which checks:
  - SHA256SUMS and `build-metadata.json` against the actual bytes;
  - that `RoofSpanSetup.exe` and `RoofSpanSetup-<ver>.exe` are identical;
  - that the embedded MSI, EDB and WebView2 payloads are byte-identical to the recorded ones;
  - the bundle and MSI versions and the MSI UpgradeCode;
  - that the packaged Relay connector reports the expected Git SHA and version.

  Next it installs that exact file offline and re-hashes it. Only then does it upload one artifact,
  `roofspan-office-installer`, containing:
  - the exe, the versioned exe, the MSI, `SHA256SUMS.txt`, `build-metadata.json`,
    `artifact-verification.json`, `ci-provenance.json` and the build logs.

  The tested SHA-256 is shown in the job summary.
- **Prerequisite payloads:** EDB 16.4-1 is pinned by SHA-256. WebView2 (Evergreen permalink, always the
  latest) must carry a valid Microsoft signature, and its exact version and hash are recorded.
- **Signing (in CI, before the install test):** configure these in the repository settings:
  - `secrets.ROOFSPAN_WINDOWS_SIGNING_PFX_BASE64`: the code-signing certificate as a base64-encoded .pfx;
  - `secrets.ROOFSPAN_WINDOWS_SIGNING_PFX_PASSWORD`: the .pfx password;
  - `vars.ROOFSPAN_UPDATE_PUBLIC_KEY_PEM`: the real Ed25519 update PUBLIC key PEM (public; a variable is fine).

  `build.ps1` signs the MSI, then the Burn engine (detach/sign/reattach), then the bundle. Without
  these, CI still builds and tests, but the artifact is marked `releasable: false` and promotion refuses it.
- **Promotion (no rebuild):** run the `release-promote` workflow by hand. Its inputs are the
  `windows-build-scripts` **push-to-main** run ID, the SHA-256 from that run's summary, and a tag. It
  checks that all seven jobs succeeded, downloads the artifact, re-verifies the hashes, provenance and
  release eligibility, and attaches the identical files to a **draft** GitHub Release. Uploading to
  S3/CloudFront remains manual.

### Required branch protection (manual GitHub setting)
In GitHub, open **Settings -> Rules -> Rulesets -> New branch ruleset**. A classic rule under
**Settings -> Branches -> Add rule** works the same way. Set the target to `main`, then enable:
1. **Require a pull request before merging**.
2. **Require status checks to pass**, with **Require branches to be up to date before merging**. Add
   these checks, with source **GitHub Actions**. They are the job IDs of `windows-build-scripts`; the
   jobs deliberately have no display `name:`:
   `bundle-compile`, `validate`, `burn-prep-runtime`, `clean-machine-full-install`,
   `services-install-smoke`, `db-bootstrap-integration`, `transactional-upgrade`.
3. **Block force pushes** and **Restrict deletions**. Leave the bypass list empty, including
   administrators.

A cancelled, skipped or failed required check then blocks the merge. This prevents what happened with
PR #122, which was merged while `clean-machine-full-install` was still running.


## Outstanding acceptance test (manual, clean VM)
CI proves: the bundle compiles; the real Burn prep/cleanup path runs (supplied + generated password) with
the production BA theme; a genuine EDB PostgreSQL + Office install offline (network blocked, source
prerequisites deleted) with the real self-contained WebView2 desktop shell + production frontend; and the
real WebView2 Evergreen Standalone installer + `/silent /install` args succeed.

STILL REQUIRES a manual clean-VM sign-off (hosted GitHub runners ship WebView2 preinstalled and it cannot
be cleanly removed): on a fresh Windows VM with BOTH PostgreSQL AND WebView2 ABSENT and networking blocked,
double-click `RoofSpanSetup.exe` and confirm the UAC prompt appears, WebView2 + PostgreSQL both install
from the embedded payloads with no internet, `RoofSpanPostgreSQL` starts, and the Office window loads.

## Guardrails
All Windows `.ps1` build scripts are ASCII-only and validated by the PowerShell parser in CI
(`.github/workflows/windows-build-scripts.yml`), plus Python regression checks in
`windows/tests/test_build_scripts.py`. Do not force-push or rewrite `main`.
