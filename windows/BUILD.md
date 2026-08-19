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
git pull origin main
git rev-parse HEAD

Remove-Item -Recurse -Force D:\AsgardSolutions\RoofSpan\_stage -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force D:\AsgardSolutions\RoofSpan\windows\installer\dist -ErrorAction SilentlyContinue

cd D:\AsgardSolutions\RoofSpan\windows\installer

.\stage.ps1 -StageDir ..\..\_stage

.\build.ps1 `
  -Version 0.2.0 `
  -StageDir ..\..\_stage `
  -PostgresInstaller "D:\AsgardSolutions\Prerequisites\PostgreSQL\postgresql-16.14-2-windows-x64.exe" `
  -WebView2Bootstrapper "D:\AsgardSolutions\Prerequisites\WebView2\MicrosoftEdgeWebview2Setup.exe"
```

## Verify artifacts
```powershell
Get-Item `
  .\dist\RoofSpanOffice-0.2.0.msi, `
  .\dist\RoofSpanSetup-0.2.0.exe, `
  .\dist\RoofSpanSetup.exe |
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
- `build.ps1`
  - Requires `-StageDir`, `-PostgresInstaller`, `-WebView2Bootstrapper`; validates WiX, the full staged
    payload, and both prerequisite installers before building. Produces the MSI, the versioned
    `RoofSpanSetup-<ver>.exe` (Burn bundle), and the stable `RoofSpanSetup.exe`.
- Installer chain (`bundle.wxs`): WebView2 Runtime (skipped if already installed) -> PostgreSQL (skipped
  if already installed) -> RoofSpan Office MSI. Both prerequisites are `Permanent` (never removed on
  RoofSpan uninstall), so existing customer machines are not needlessly reinstalled.

## Guardrails
All Windows `.ps1` build scripts are ASCII-only and validated by the PowerShell parser in CI
(`.github/workflows/windows-build-scripts.yml`), plus Python regression checks in
`windows/tests/test_build_scripts.py`. Do not force-push or rewrite `main`.
