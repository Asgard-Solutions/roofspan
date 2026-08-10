# Builds the RoofSpan Office MSI + RoofSpanSetup.exe (Burn bundle) on Windows 10/11 x64.
# HUMAN REQUIRED: run on Windows with WiX Toolset v4 (`dotnet tool install --global wix`) and a
# production Authenticode code-signing certificate. Do NOT commit certificates or private keys.
#
#   .\build.ps1 -Version 1.0.0 -StageDir ..\..\_stage [-SignCertThumbprint <thumb>] [-UpdateSigningPrivateKey <path>]
param(
  [Parameter(Mandatory=$true)][string]$Version,
  [Parameter(Mandatory=$true)][string]$StageDir,     # staged backend/frontend/updater/runtime trees
  [string]$SignCertThumbprint = "",                  # HUMAN REQUIRED for production
  [string]$UpdateSigningPrivateKey = "",             # SEPARATE from entitlement keys; kept OFFLINE
  [string]$OutDir = ".\dist"
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "==> Building RoofSpan Office $Version"
# 1) MSI
wix build .\RoofSpan.wxs -arch x64 -d "Version=$Version" -d "StageDir=$StageDir" `
  -ext WixToolset.Util.wixext -ext WixToolset.Firewall.wixext `
  -o "$OutDir\RoofSpanOffice-$Version.msi"

# 2) Burn bundle -> customer-facing RoofSpanSetup.exe (bundles VC++ runtime + PostgreSQL prereq).
wix build .\bundle.wxs -arch x64 -d "Version=$Version" -d "MsiPath=$OutDir\RoofSpanOffice-$Version.msi" `
  -ext WixToolset.Bal.wixext -o "$OutDir\RoofSpanSetup-$Version.exe"

# 3) Authenticode signing (HUMAN REQUIRED). SmartScreen reputation builds on a real EV/OV cert.
if ($SignCertThumbprint) {
  Write-Host "==> Signing installer with cert $SignCertThumbprint"
  signtool sign /sha1 $SignCertThumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
    "$OutDir\RoofSpanSetup-$Version.exe"
} else {
  Write-Warning "UNSIGNED build (dev/test only). Production release MUST be Authenticode-signed."
}

# 4) Produce the signed UPDATE manifest (latest.json) for the CloudFront /update path.
if ($UpdateSigningPrivateKey) {
  python ..\release\make_manifest.py `
    --version $Version `
    --installer "$OutDir\RoofSpanSetup-$Version.exe" `
    --min-supported "1.0.0" `
    --signing-key $UpdateSigningPrivateKey `
    --out "$OutDir\latest.json"
}

# 5) Copy to the stable name expected at downloads.roofspan.io/latest/
Copy-Item "$OutDir\RoofSpanSetup-$Version.exe" "$OutDir\RoofSpanSetup.exe" -Force
Write-Host "==> Artifacts in $OutDir :"
Write-Host "    RoofSpanSetup.exe            -> upload to /latest/"
Write-Host "    RoofSpanSetup-$Version.exe   -> upload to /releases/"
Write-Host "    latest.json                  -> upload to /update/windows/ (if generated)"
Write-Host "HUMAN REQUIRED: upload artifacts to the approved private S3 behind CloudFront."
