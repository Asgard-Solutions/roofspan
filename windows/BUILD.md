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
- **Triggers:** every pull request into `main` runs all six Windows jobs (there is no path filter, so
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
  checks that all six jobs succeeded, downloads the artifact, re-verifies the hashes, provenance and
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
   `services-install-smoke`, `db-bootstrap-integration`.
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
