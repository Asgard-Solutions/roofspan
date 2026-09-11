# Builds RoofSpanOffice-{VERSION}.msi + RoofSpanSetup-{VERSION}.exe (Burn bundle) + RoofSpanSetup.exe.
# HUMAN REQUIRED: run on Windows 10/11 x64 with the WiX Toolset 5.0.2 (`dotnet tool install --global wix --version 5.0.2`),
# the staged tree (installer\stage.ps1), the EDB PostgreSQL installer, the FULL WebView2 Evergreen
# Standalone x64 installer, and (for release) an Authenticode certificate + the offline update-signing
# private key. Do NOT commit certificates or private keys.
#
#   .\stage.ps1  -StageDir ..\..\_stage -UpdatePublicKey <pub.pem>
#   .\build.ps1  -StageDir ..\..\_stage -PostgresInstaller C:\prereq\postgresql-16-windows-x64.exe `
#                -WebView2StandaloneInstaller C:\prereq\MicrosoftEdgeWebView2RuntimeInstallerX64.exe `
#                [-Version <windows\VERSION>] [-SignCertThumbprint <thumb>] [-UpdateSigningPrivateKey <priv.pem>]
param(
  [string]$Version = "",
  [Parameter(Mandatory=$true)][string]$StageDir,
  [Parameter(Mandatory=$true)][string]$PostgresInstaller,
  [Parameter(Mandatory=$true)][string]$WebView2StandaloneInstaller,
  [string]$SignCertThumbprint = "",
  [string]$UpdateSigningPrivateKey = "",
  [string]$OutDir = ".\dist"
)
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$versionFile = Join-Path $repoRoot "windows\VERSION"
$canonicalVersion = (Get-Content $versionFile -Raw).Trim()
if (-not $Version) {
  $Version = $canonicalVersion
} elseif ($Version -ne $canonicalVersion) {
  throw "Build version '$Version' does not match windows\VERSION '$canonicalVersion'. Update windows\VERSION first; version overrides are not allowed for customer-traceable builds."
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
  throw "RoofSpan version must be a three-part numeric version; found '$Version'."
}

if (-not [System.IO.Path]::IsPathRooted($StageDir)) {
  $StageDir = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $StageDir))
} else {
  $StageDir = [System.IO.Path]::GetFullPath($StageDir)
}

$gitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $gitSha -notmatch '^[0-9a-fA-F]{40}$') {
  throw "Unable to resolve the source Git SHA; refusing to build an untraceable installer."
}

function Assert-RelayConnectorBuildInfo {
  param(
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$ExpectedSha,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion
  )

  $output = @(& $ExePath --build-info)
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "Staged Relay connector build-info probe failed (exit $exitCode). Remove _stage and run stage.ps1 again."
  }
  $jsonLine = $output | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
  if (-not $jsonLine) {
    throw "Staged Relay connector does not expose the required build contract. Remove _stage and run stage.ps1 again."
  }
  try {
    $info = $jsonLine | ConvertFrom-Json
  } catch {
    throw "Staged Relay connector returned invalid build-info JSON. Remove _stage and run stage.ps1 again."
  }

  if ($info.service -ne "roofspan-relay-connector" -or
      $info.build_sha -ne $ExpectedSha -or
      $info.version -ne $ExpectedVersion -or
      $info.contract -ne "hosted-installation-identity-v2" -or
      $info.identity_endpoint -ne "/api/relay/connector/identity" -or
      $info.installation_relay_path -ne "/api/relay/installation") {
    throw "Staged Relay connector is stale or mismatched. Expected SHA=$ExpectedSha version=$ExpectedVersion hosted-installation-identity-v2; found SHA=$($info.build_sha) version=$($info.version) contract=$($info.contract). Remove _stage and run stage.ps1 again."
  }
  Write-Host "==> Verified staged Relay connector: SHA=$($info.build_sha) version=$($info.version) contract=$($info.contract)"
}

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
  throw "WiX not found. Install: dotnet tool install --global wix --version 5.0.2"
}

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

$relayExe = Join-Path $StageDir "services\roofspan-relay-connector\roofspan-relay-connector.exe"
$required = @(
  (Join-Path $StageDir "services\roofspan-backend\roofspan-backend.exe"),
  $relayExe,
  (Join-Path $StageDir "services\roofspan-update-service\roofspan-update-service.exe"),
  (Join-Path $StageDir "frontend\index.html"),
  (Join-Path $StageDir "shell\RoofSpanOffice.exe"),
  (Join-Path $StageDir "runtime\RoofSpan.ico"),
  (Join-Path $StageDir "config-templates")
)
foreach ($p in $required) {
  if (-not (Test-Path $p)) { throw "Staging incomplete - missing '$p'. Run installer\stage.ps1 first." }
}
Assert-RelayConnectorBuildInfo -ExePath $relayExe -ExpectedSha $gitSha -ExpectedVersion $Version

if (-not (Test-Path $PostgresInstaller)) {
  throw "PostgreSQL prerequisite installer not found at '$PostgresInstaller'."
}
if (-not (Test-Path $WebView2StandaloneInstaller)) {
  throw "WebView2 Evergreen Standalone installer not found at '$WebView2StandaloneInstaller'. Download the FULL x64 runtime (MicrosoftEdgeWebView2RuntimeInstallerX64.exe) from https://developer.microsoft.com/microsoft-edge/webview2/ (Evergreen Standalone Installer, x64). The small MicrosoftEdgeWebview2Setup.exe download bootstrapper is NOT accepted - it requires internet at install time."
}

# Build into a CLEAN, isolated staging output first so a failed rebuild can never publish or copy an
# older installer as the new output. Only after a fully successful build do we promote artifacts into
# $OutDir and refresh the stable RoofSpanSetup.exe name.
$stagingOut = Join-Path $OutDir ("_build-" + $Version)
if (Test-Path $stagingOut) { Remove-Item -Recurse -Force $stagingOut }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $stagingOut | Out-Null
$msi   = Join-Path $stagingOut "RoofSpanOffice-$Version.msi"
$setup = Join-Path $stagingOut "RoofSpanSetup-$Version.exe"

Write-Host "==> Building RoofSpan Office $Version from $gitSha"

# 1) MSI (payload harvested from $StageDir, including the native application shell).
wix build .\RoofSpan.wxs -arch x64 -d "Version=$Version" -d "StageDir=$StageDir" `
  -ext WixToolset.Util.wixext -ext WixToolset.Firewall.wixext -o $msi
if ($LASTEXITCODE -ne 0) { throw "MSI compile failed (wix exit $LASTEXITCODE)." }
if (-not (Test-Path $msi)) { throw "MSI build failed: $msi not produced." }

# 2) Burn bundle -> customer-facing RoofSpanSetup.exe (WebView2 + PostgreSQL + Office MSI).
wix build .\bundle.wxs -arch x64 -d "Version=$Version" -d "MsiPath=$msi" `
  -d "PostgresInstaller=$PostgresInstaller" `
  -d "WebView2StandaloneInstaller=$WebView2StandaloneInstaller" `
  -ext WixToolset.BootstrapperApplications.wixext -ext WixToolset.Util.wixext -o $setup
if ($LASTEXITCODE -ne 0) { throw "Bundle compile failed (wix exit $LASTEXITCODE)." }
if (-not (Test-Path $setup)) { throw "Bundle build failed: $setup not produced." }

# 3) Authenticode signing.
if ($SignCertThumbprint) {
  Write-Host "==> Signing $setup"
  signtool sign /sha1 $SignCertThumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 $setup
  if ($LASTEXITCODE -ne 0) { throw "signtool failed (exit $LASTEXITCODE); refusing to publish an unsigned or partially-signed installer." }
} else {
  Write-Warning "UNSIGNED build (dev/test only). Production release MUST be Authenticode-signed."
}

# 4) Signed UPDATE manifest.
if ($UpdateSigningPrivateKey) {
  python ..\release\make_manifest.py --version $Version --installer $setup `
    --min-supported $Version --signing-key $UpdateSigningPrivateKey --out (Join-Path $stagingOut "latest.json")
  if ($LASTEXITCODE -ne 0) { throw "Update manifest generation failed (exit $LASTEXITCODE)." }
}

# 5) Promote the just-built artifacts into $OutDir and refresh the stable name. Because we built into an
#    isolated folder and every native step above is exit-code checked, an older installer can never be
#    republished as the new output. The stable RoofSpanSetup.exe is replaced ONLY on full success.
$finalMsi   = Join-Path $OutDir "RoofSpanOffice-$Version.msi"
$finalSetup = Join-Path $OutDir "RoofSpanSetup-$Version.exe"
$stableSetup = Join-Path $OutDir "RoofSpanSetup.exe"
Copy-Item $msi $finalMsi -Force
Copy-Item $setup $finalSetup -Force
Copy-Item $setup $stableSetup -Force
if ($UpdateSigningPrivateKey) { Copy-Item (Join-Path $stagingOut "latest.json") (Join-Path $OutDir "latest.json") -Force }
Remove-Item -Recurse -Force $stagingOut

# 6) Report the exact release identity so the file under test is unambiguous.
$setupItem = Get-Item $finalSetup
$setupHash = (Get-FileHash $finalSetup -Algorithm SHA256).Hash
$setupMB = [math]::Round($setupItem.Length / 1MB, 2)
Write-Host "==> Artifacts in $OutDir :"
Write-Host "    RoofSpanOffice-$Version.msi"
Write-Host "    RoofSpanSetup-$Version.exe   -> upload to /releases/"
Write-Host "    RoofSpanSetup.exe            -> upload to /latest/"
if ($UpdateSigningPrivateKey) { Write-Host "    latest.json                  -> upload to /update/windows/" }
Write-Host ""
Write-Host "==> Release identity (verify this exact file is what you test/ship):"
Write-Host "    Version   : $Version"
Write-Host "    Git SHA   : $gitSha"
Write-Host "    Artifact  : RoofSpanSetup-$Version.exe"
Write-Host "    Size      : $($setupItem.Length) bytes ($setupMB MB)"
Write-Host "    SHA-256   : $setupHash"
Write-Host "HUMAN REQUIRED: upload artifacts to the approved private S3 behind CloudFront."
