# Builds RoofSpanOffice-{VERSION}.msi + RoofSpanSetup-{VERSION}.exe (Burn bundle) + RoofSpanSetup.exe.
# HUMAN REQUIRED: run on Windows 10/11 x64 with WiX Toolset v5 (`dotnet tool install --global wix --version 5.*`),
# Visual Studio 2022 Desktop C++ (to compile the BAFunctions DLL), the staged tree (installer\stage.ps1),
# the EDB PostgreSQL installer, and (for release) an Authenticode certificate + the offline update-signing
# private key. Do NOT commit certificates or private keys.
#
#   .\stage.ps1  -StageDir ..\..\_stage -UpdatePublicKey <pub.pem>
#   .\build.ps1  -StageDir ..\..\_stage -PostgresInstaller C:\prereq\postgresql-16-windows-x64.exe `
#                [-Version 0.1.0] [-BaFunctionsDll <override.dll>] [-SignCertThumbprint <thumb>] `
#                [-UpdateSigningPrivateKey <priv.pem>]
# By default the BAFunctions DLL is built automatically from windows\bafunctions\ (no manual pre-build);
# -BaFunctionsDll is an optional CI/override to consume a pre-built DLL.
param(
  [string]$Version = "",                                       # defaults to windows/VERSION
  [Parameter(Mandatory=$true)][string]$StageDir,               # from stage.ps1
  [Parameter(Mandatory=$true)][string]$PostgresInstaller,      # EDB PostgreSQL silent installer (.exe)
  [string]$BaFunctionsDll = "",                                # optional override; auto-built if empty
  [string]$SignCertThumbprint = "",                            # HUMAN REQUIRED for production
  [string]$UpdateSigningPrivateKey = "",                       # SEPARATE from entitlement keys; OFFLINE
  [string]$OutDir = ".\dist"
)
$ErrorActionPreference = "Stop"
if (-not $Version) { $Version = (Get-Content (Join-Path $PSScriptRoot "..\VERSION") -Raw).Trim() }

# ---- FAIL-FAST: required tooling, staged payload, and prerequisites must all exist. No partial builds.
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
  throw "WiX v5 not found. Install: dotnet tool install --global wix --version 5.*"
}
$required = @(
  (Join-Path $StageDir "services\roofspan-backend.exe"),
  (Join-Path $StageDir "services\roofspan-relay-connector.exe"),
  (Join-Path $StageDir "services\roofspan-update-service.exe"),
  (Join-Path $StageDir "frontend\index.html"),
  (Join-Path $StageDir "runtime"),
  (Join-Path $StageDir "config-templates")
)
foreach ($p in $required) {
  if (-not (Test-Path $p)) { throw "Staging incomplete — missing '$p'. Run installer\stage.ps1 first." }
}
# The deferred DB bootstrap tool MUST be staged (WiX packages tools\RoofSpanBootstrap.exe).
$bootstrapExe = Join-Path $StageDir "tools\RoofSpanBootstrap.exe"
if (-not (Test-Path $bootstrapExe)) {
  throw "Staging incomplete — missing '$bootstrapExe'. Run installer\stage.ps1 first."
}

# ---- STALENESS GUARD: a rebuild of the MSI must NOT silently package PyInstaller exes that are older than
# their Python sources (e.g. re-running build.ps1 after editing bootstrap_db.py without re-staging). Fail
# fast and tell the operator to re-run stage.ps1.
$pySources = @()
$pySources += Get-ChildItem (Join-Path $PSScriptRoot "..\winbuild") -Filter *.py -File -Recurse
$pySources += Get-ChildItem (Join-Path $PSScriptRoot "..\..\backend") -Filter *.py -File -Recurse
$newestSrc = ($pySources | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
$stagedExes = @()
$stagedExes += Get-ChildItem (Join-Path $StageDir "services") -Filter *.exe -File -ErrorAction SilentlyContinue
$stagedExes += Get-ChildItem (Join-Path $StageDir "tools") -Filter *.exe -File -ErrorAction SilentlyContinue
$stale = $stagedExes | Where-Object { $_.LastWriteTimeUtc -lt $newestSrc }
if ($stale) {
  throw ("Stale staged executable(s) older than current Python sources: " +
         ($stale.Name -join ', ') +
         ". Re-run installer\stage.ps1 (rebuilds PyInstaller exes) before build.ps1.")
}
if (-not (Test-Path $PostgresInstaller)) {
  throw "PostgreSQL prerequisite installer not found at '$PostgresInstaller'."
}

# ---- BAFunctions DLL: build it here so a normal installer build is self-contained (K.I.S.S.). It
# CSPRNG-generates PgSuperPassword before the PostgreSQL prerequisite runs. Override via -BaFunctionsDll.
if (-not $BaFunctionsDll) {
  Write-Host "==> Building RoofSpan BAFunctions DLL (windows\bafunctions\)"
  $BaFunctionsDll = & (Join-Path $PSScriptRoot "..\bafunctions\build_bafunctions.ps1") -Configuration Release -Platform x64 |
    Select-Object -Last 1
}
if (-not (Test-Path $BaFunctionsDll)) {
  throw "BAFunctions DLL not found at '$BaFunctionsDll' (build via windows\bafunctions\build_bafunctions.ps1)."
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$msi = Join-Path $OutDir "RoofSpanOffice-$Version.msi"
$setup = Join-Path $OutDir "RoofSpanSetup-$Version.exe"

Write-Host "==> Building RoofSpan Office $Version"

# 1) MSI (payload harvested from $StageDir). WiX v5 extensions, pinned to the 5.0.2 toolset.
wix build .\RoofSpan.wxs -arch x64 -d "Version=$Version" -d "StageDir=$StageDir" `
  -ext WixToolset.Util.wixext/5.0.2 -ext WixToolset.Firewall.wixext/5.0.2 -o $msi
if (-not (Test-Path $msi)) { throw "MSI build failed: $msi not produced." }

# 2) Burn bundle -> customer-facing RoofSpanSetup.exe (chains PostgreSQL prereq + MSI).
# WiX v5 renamed the BAL extension for wix.exe to WixToolset.BootstrapperApplications.wixext
# (the older Bal.wixext id is retained mainly for MSBuild PackageReference compatibility).
wix build .\bundle.wxs -arch x64 -d "Version=$Version" -d "MsiPath=$msi" `
  -d "PostgresInstaller=$PostgresInstaller" -d "BaFunctionsDll=$BaFunctionsDll" `
  -ext WixToolset.BootstrapperApplications.wixext/5.0.2 -ext WixToolset.Util.wixext/5.0.2 -o $setup
if (-not (Test-Path $setup)) { throw "Bundle build failed: $setup not produced." }

# 3) Authenticode signing (HUMAN REQUIRED for production; SmartScreen reputation needs a real EV/OV cert).
if ($SignCertThumbprint) {
  Write-Host "==> Signing $setup"
  signtool sign /sha1 $SignCertThumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 $setup
} else {
  Write-Warning "UNSIGNED build (dev/test only). Production release MUST be Authenticode-signed."
}

# 4) Signed UPDATE manifest (latest.json) for the CloudFront /update path.
if ($UpdateSigningPrivateKey) {
  python ..\release\make_manifest.py --version $Version --installer $setup `
    --min-supported $Version --signing-key $UpdateSigningPrivateKey --out (Join-Path $OutDir "latest.json")
}

# 5) Stable name expected at downloads.roofspan.io/latest/.
Copy-Item $setup (Join-Path $OutDir "RoofSpanSetup.exe") -Force
Write-Host "==> Artifacts in $OutDir :"
Write-Host "    RoofSpanOffice-$Version.msi"
Write-Host "    RoofSpanSetup-$Version.exe   -> upload to /releases/"
Write-Host "    RoofSpanSetup.exe            -> upload to /latest/"
Write-Host "    latest.json                  -> upload to /update/windows/ (if generated)"
Write-Host "HUMAN REQUIRED: upload artifacts to the approved private S3 behind CloudFront."
