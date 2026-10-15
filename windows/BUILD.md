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

## Local Office build and CI prerequisite parity

Both Windows CI pipelines call the same production staging/build scripts as the documented developer workflow: `windows/installer/stage.ps1` and `build.ps1`. The production stage includes FOUR PyInstaller executables (backend, relay connector, update service and update broker), plus frontend, native WebView2 shell, icon, templates and upgrade coordinator.

**The PostgreSQL prerequisite must match the one shipped to customers.** Historically, CI used EDB 16.4-1, whereas the documented local test build uses `postgresql-16.14-2-windows-x64.exe`. CI defaults to the previously verified EDB 16.4-1 SHA-256. To test the exact local/release prerequisite, configure BOTH GitHub repository variables:

- `ROOFSPAN_CI_EDB_URL` = `https://get.enterprisedb.com/postgresql/postgresql-16.14-2-windows-x64.exe` (verify the official download actually exists)
- `ROOFSPAN_CI_EDB_SHA256` = SHA-256 of that SAME trusted local installer, from `Get-FileHash -Algorithm SHA256` (never guess it)

Either configure both or neither. The shared `windows/installer/Get-CIPostgreSQLInstaller.ps1` checks the versioned official HTTPS URL, SHA-256 and EnterpriseDB Authenticode signature and rejects partial overrides. Both Windows workflows use it. GitHub CI cannot read the local `D:\AsgardSolutions\Prerequisites` folder.

Use the FULL x64 WebView2 Evergreen Standalone installer, **not** the web bootstrapper. CI verifies its size and publisher and records the embedded version/hash. Evergreen bits may change between builds.

Unsigned builds without a real update public key are for development/test only, not release. Release promotion additionally requires Authenticode signatures, update signing configuration, completed acceptance checks and the exactly tested artifact. Automated backend/service readiness does NOT cover interactive Office desktop login, dashboard, maps, settings, or mobile/relay UI behavior; record separate UI acceptance evidence.

## Installer failure-injection matrix (`.github/workflows/windows-installer-matrix.yml`)
One production `RoofSpanSetup.exe` is built (no fault injection), verified, hashed and uploaded once. Every
scenario job downloads those bytes and refuses to run if the SHA-256 differs. Hosted scenarios each get a fresh
`windows-latest` runner. Failures are injected from OUTSIDE the product (ACL-denied PostgreSQL tools, a 64 MB
VHDX backup volume, port holders, PostgreSQL triggers armed after the verified backup, killed processes), so
the tested binary is the customer binary. Catalog: `windows/tests/matrix/scenarios.json`; controller:
`matrix.py`; harness: `MatrixLib.psm1` + `Invoke-MatrixScenario.ps1`.

- **Safety guard**: `matrix.py guard` refuses unless `ROOFSPAN_MATRIX_DESTRUCTIVE=I-UNDERSTAND-THIS-DESTROYS-ROOFSPAN-DATA`
  AND either a GitHub-hosted Windows runner OR an approved single-use VM (see below). Nothing is touched before it passes.
- **Baselines** (upgrade + upgrade-failure scenarios): set repository variables `ROOFSPAN_BASELINE_N1_URL`,
  `ROOFSPAN_BASELINE_N1_SHA256`, `ROOFSPAN_BASELINE_N1_VERSION` (and `_N2_`), or pass them as
  `workflow_dispatch` inputs. Missing => `BLOCKED_MISSING_BASELINE`. A partial/invalid configuration fails the plan.
- **Disposable VM** (`webview2-absent-offline`, `uac-different-admin`, `low-resource-large-db`): set
  `vars.ROOFSPAN_DISPOSABLE_VM_ENABLED=true` and register an `--ephemeral` self-hosted runner with labels
  `self-hosted, Windows, roofspan-disposable-vm, <scenario-id>` (use exactly one of the three scenario IDs).
  The job requires that exact scenario label; a runner prepared for another scenario must not receive it.
  Run in an interactive desktop session, and revert to a clean snapshot after every job.
  The image must contain `C:\ProgramData\RoofSpanDisposableVM\approved.json`
  = `{"purpose":"roofspan-installer-matrix","disposable":true,"machine_guid":"<HKLM\SOFTWARE\Microsoft\Cryptography MachineGuid>"}`.
  Every VM baseline needs no PostgreSQL, Python 3.11 and pwsh. The `webview2-absent-offline` baseline additionally
  must have no WebView2 runtime. `uac-different-admin` also needs secrets
  `ROOFSPAN_VM_APPROVER_USER`/`_PASSWORD` (a second local administrator) and `ConsentPromptBehaviorAdmin=0`
  so the approval can be automated. `low-resource-large-db` needs <= 4.5 GB RAM, <= 2 vCPU
  (`vars.ROOFSPAN_MATRIX_DB_GB`, default 2). Otherwise these scenarios are `PENDING_VM`.
- **Results**: each job uploads `matrix-result-<scenario>` (assertions, sanitized before/after manifests,
  Burn/MSI/service/migration/backup logs, Event Log extract, versions, scrub report) with `if: always()`.
  The `summary` job writes the matrix table to the run summary and fails on any FAIL; on a release build
  (`release_build` input or a `v*` tag) it also fails on PENDING/BLOCKED/SKIP.


## Guardrails
All Windows `.ps1` build scripts are ASCII-only and validated by the PowerShell parser in CI
(`.github/workflows/windows-build-scripts.yml`), plus Python regression checks in
`windows/tests/test_build_scripts.py`. Do not force-push or rewrite `main`.
