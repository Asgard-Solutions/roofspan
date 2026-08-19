# Builds RoofSpanOffice-{VERSION}.msi + RoofSpanSetup-{VERSION}.exe (Burn bundle) + RoofSpanSetup.exe.
# HUMAN REQUIRED: run on Windows 10/11 x64 with the WiX Toolset 5.0.2 (`dotnet tool install --global wix --version 5.0.2`),
# the staged tree (installer\stage.ps1), the EDB PostgreSQL installer, and (for release) an Authenticode
# certificate + the offline update-signing private key. Do NOT commit certificates or private keys.
#
#   .\stage.ps1  -StageDir ..\..\_stage -UpdatePublicKey <pub.pem>
#   .\build.ps1  -StageDir ..\..\_stage -PostgresInstaller C:\prereq\postgresql-16-windows-x64.exe `
#                [-Version 0.1.0] [-SignCertThumbprint <thumb>] [-UpdateSigningPrivateKey <priv.pem>]
param(
  [string]$Version = "",                                       # defaults to windows/VERSION
  [Parameter(Mandatory=$true)][string]$StageDir,               # from stage.ps1
  [Parameter(Mandatory=$true)][string]$PostgresInstaller,      # EDB PostgreSQL silent installer (.exe)
  [Parameter(Mandatory=$true)][string]$WebView2Bootstrapper,   # Evergreen WebView2 runtime bootstrapper (.exe)
  [string]$SignCertThumbprint = "",                            # HUMAN REQUIRED for production
  [string]$UpdateSigningPrivateKey = "",                       # SEPARATE from entitlement keys; OFFLINE
  [string]$OutDir = ".\dist"
)
$ErrorActionPreference = "Stop"
if (-not $Version) { $Version = (Get-Content (Join-Path $PSScriptRoot "..\VERSION") -Raw).Trim() }

# ---- FAIL-FAST: required tooling, staged payload, and prerequisites must all exist. No partial builds.
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
  throw "WiX not found. Install: dotnet tool install --global wix --version 5.0.2"
}

# ---- Deterministically restore the EXACT WiX 5.0.2 CLI extensions this build requires.
# WiX 5 renamed WixToolset.Bal.wixext -> WixToolset.BootstrapperApplications.wixext for CLI use;
# the old 'Bal' package is retained only for MSBuild PackageReference back-compat and installs as
# 'damaged' via the CLI. We standardize on the renamed package, pinned to the WiX tool version 5.0.2.
$WixExtVersion = "5.0.2"
$RequiredWixExtensions = @(
  "WixToolset.BootstrapperApplications.wixext",
  "WixToolset.Util.wixext",
  "WixToolset.Firewall.wixext"
)
$installedExtensions = (& wix extension list -g 2>$null)
foreach ($ext in $RequiredWixExtensions) {
  $wanted = "$ext/$WixExtVersion"
  $present = $installedExtensions | Where-Object { $_ -match [regex]::Escape($ext) -and $_ -match [regex]::Escape($WixExtVersion) }
  if (-not $present) {
    Write-Host "==> Restoring WiX extension $wanted"
    & wix extension add -g $wanted
    if ($LASTEXITCODE -ne 0) { throw "Failed to restore required WiX extension '$wanted'. Aborting build." }
  } else {
    Write-Host "==> WiX extension present: $wanted"
  }
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
  if (-not (Test-Path $p)) { throw "Staging incomplete - missing '$p'. Run installer\stage.ps1 first." }
}
if (-not (Test-Path $PostgresInstaller)) {
  throw "PostgreSQL prerequisite installer not found at '$PostgresInstaller'."
}
if (-not (Test-Path $WebView2Bootstrapper)) {
  throw "WebView2 bootstrapper not found at '$WebView2Bootstrapper'. Download MicrosoftEdgeWebview2Setup.exe."
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$msi = Join-Path $OutDir "RoofSpanOffice-$Version.msi"
$setup = Join-Path $OutDir "RoofSpanSetup-$Version.exe"

Write-Host "==> Building RoofSpan Office $Version"

# 1) MSI (payload harvested from $StageDir).
wix build .\RoofSpan.wxs -arch x64 -d "Version=$Version" -d "StageDir=$StageDir" `
  -ext WixToolset.Util.wixext -ext WixToolset.Firewall.wixext -o $msi
if (-not (Test-Path $msi)) { throw "MSI build failed: $msi not produced." }

# 2) Burn bundle -> customer-facing RoofSpanSetup.exe (chains WebView2 + PostgreSQL prereqs + MSI).
wix build .\bundle.wxs -arch x64 -d "Version=$Version" -d "MsiPath=$msi" `
  -d "PostgresInstaller=$PostgresInstaller" `
  -d "WebView2Bootstrapper=$WebView2Bootstrapper" `
  -ext WixToolset.BootstrapperApplications.wixext -ext WixToolset.Util.wixext -o $setup
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
