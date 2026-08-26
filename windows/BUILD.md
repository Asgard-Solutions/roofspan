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
- Prerequisite installers (not committed):
  - PostgreSQL: `D:\AsgardSolutions\Prerequisites\PostgreSQL\postgresql-16.14-2-windows-x64.exe`
  - WebView2:   `D:\AsgardSolutions\Prerequisites\WebView2\MicrosoftEdgeWebview2Setup.exe`

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
  -WebView2Bootstrapper "D:\AsgardSolutions\Prerequisites\WebView2\MicrosoftEdgeWebview2Setup.exe"
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
  - Requires `-StageDir`, `-PostgresInstaller`, `-WebView2Bootstrapper`; validates WiX, the full staged
    payload, and both prerequisite installers before building.
  - Re-runs the Relay connector build-info probe and refuses an old `_stage`, a mismatched source SHA, or
    a version that differs from `windows\VERSION`.
  - Produces the MSI, the versioned `RoofSpanSetup-<ver>.exe` Burn bundle, and `RoofSpanSetup.exe`.
- Installer chain (`bundle.wxs`): WebView2 Runtime (skipped if already installed) -> PostgreSQL (skipped
  if already installed) -> RoofSpan Office MSI. Both prerequisites are `Permanent` (never removed on
  RoofSpan uninstall), so existing customer machines are not needlessly reinstalled.

## Relay connector verification
After installation, this command must report the build SHA used for the installer, the current version,
and contract `hosted-installation-identity-v2`:

```powershell
& "C:\Program Files\RoofSpan Office\services\roofspan-relay-connector\roofspan-relay-connector.exe" --build-info
```

The current connector log starts with `relay: outbound connector loop started` and includes its build SHA.
A log that says only `relay: outbound tunnel loop started -> .../api/relay/tunnel` identifies a pre-v2
connector and must not be accepted as a current customer build.

## Guardrails
All Windows `.ps1` build scripts are ASCII-only and validated by the PowerShell parser in CI
(`.github/workflows/windows-build-scripts.yml`), plus Python regression checks in
`windows/tests/test_build_scripts.py`. Do not force-push or rewrite `main`.
