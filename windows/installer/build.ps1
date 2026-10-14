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
  (Join-Path $StageDir "services\roofspan-update-broker\roofspan-update-broker.exe"),
  (Join-Path $StageDir "frontend\index.html"),
  (Join-Path $StageDir "shell\RoofSpanOffice.exe"),
  (Join-Path $StageDir "runtime\RoofSpan.ico"),
  (Join-Path $StageDir "config-templates")
)
foreach ($p in $required) {
  if (-not (Test-Path $p)) { throw "Staging incomplete - missing '$p'. Run installer\stage.ps1 first." }
}
Assert-RelayConnectorBuildInfo -ExePath $relayExe -ExpectedSha $gitSha -ExpectedVersion $Version
# Every staged service executable must carry the immutable build identity of THIS source + version.
# WiX must package exactly the executables build_exes.ps1 produced for THIS source + version.
Import-Module (Join-Path $PSScriptRoot "ServicesBuild.psm1") -Force
$requiredServices = Get-RoofSpanRequiredServices
$servicesManifest = Assert-ServicesBuildManifest -ServicesDir (Join-Path $StageDir "services") -Version $Version -GitSha $gitSha
foreach ($svcName in $requiredServices) {
  $svcExe = Join-Path $StageDir "services\$svcName\$svcName.exe"
  $lines = @(& $svcExe --build-info)
  if ($LASTEXITCODE -ne 0) { throw "Staged $svcName --build-info failed (exit $LASTEXITCODE). Remove _stage and run stage.ps1 again." }
  $line = $lines | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
  $bi = if ($line) { $line | ConvertFrom-Json } else { $null }
  if (-not $bi -or $bi.service -ne $svcName -or $bi.build_sha -ne $gitSha -or $bi.version -ne $Version -or
      $bi.build_contract -ne "roofspan-build-identity-v1" -or $bi.embedded -ne $true) {
    throw "Staged $svcName build identity is stale or mismatched (expected SHA=$gitSha version=$Version; found $line). Remove _stage and run stage.ps1 again."
  }
  Write-Host "==> Verified staged $svcName build identity: SHA=$($bi.build_sha) version=$($bi.version)"
}

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

function Resolve-SignTool {
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
  $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
  if (-not $found) { throw "signtool.exe not found (install the Windows SDK); refusing to produce an unsigned release." }
  return $found.FullName
}

function Invoke-Sign([string]$Path, [string]$What) {
  Write-Host "==> Signing $What ($Path)"
  & $script:SignTool sign /sha1 $SignCertThumbprint /fd sha256 /tr http://timestamp.digicert.com /td sha256 /d "RoofSpan Office" $Path
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $What (exit $LASTEXITCODE); refusing to publish an unsigned or partially-signed installer." }
  $sig = Get-AuthenticodeSignature -FilePath $Path
  if ($sig.Status -ne 'Valid') { throw "Authenticode signature on $What is not valid ($($sig.Status)); refusing to publish." }
}

if ($SignCertThumbprint) { $script:SignTool = Resolve-SignTool }

# 1) MSI (payload harvested from $StageDir, including the native application shell).
wix build .\RoofSpan.wxs -arch x64 -d "Version=$Version" -d "StageDir=$StageDir" `
  -ext WixToolset.Util.wixext -ext WixToolset.Firewall.wixext -o $msi
if ($LASTEXITCODE -ne 0) { throw "MSI compile failed (wix exit $LASTEXITCODE)." }
if (-not (Test-Path $msi)) { throw "MSI build failed: $msi not produced." }
# The MSI is signed BEFORE the bundle is built because Burn records the embedded MSI's hash.
if ($SignCertThumbprint) { Invoke-Sign $msi "Office MSI" }

# 2) Burn bundle -> customer-facing RoofSpanSetup.exe (WebView2 + PostgreSQL + Office MSI).
$upgradeExe = Join-Path $StageDir "upgrade\roofspan-upgrade.exe"
if (-not (Test-Path $upgradeExe)) { throw "Staged upgrade coordinator missing: $upgradeExe. Run stage.ps1 again." }
wix build .\bundle.wxs -arch x64 -d "Version=$Version" -d "MsiPath=$msi" -d "UpgradeExe=$upgradeExe" `
  -d "PostgresInstaller=$PostgresInstaller" `
  -d "WebView2StandaloneInstaller=$WebView2StandaloneInstaller" `
  -ext WixToolset.BootstrapperApplications.wixext -ext WixToolset.Util.wixext -o $setup
if ($LASTEXITCODE -ne 0) { throw "Bundle compile failed (wix exit $LASTEXITCODE)." }
if (-not (Test-Path $setup)) { throw "Bundle build failed: $setup not produced." }

# 3) Authenticode signing. A Burn bundle's elevated engine must be signed too: detach the engine, sign
#    it, reattach it, then sign the complete bundle.
if ($SignCertThumbprint) {
  $engine = Join-Path $stagingOut "burn-engine.exe"
  $reattached = Join-Path $stagingOut "RoofSpanSetup-$Version.reattached.exe"
  wix burn detach $setup -engine $engine
  if ($LASTEXITCODE -ne 0) { throw "wix burn detach failed (exit $LASTEXITCODE)." }
  Invoke-Sign $engine "Burn engine"
  wix burn reattach $setup -engine $engine -o $reattached
  if ($LASTEXITCODE -ne 0) { throw "wix burn reattach failed (exit $LASTEXITCODE)." }
  Move-Item -Force $reattached $setup
  Remove-Item -Force $engine
  Invoke-Sign $setup "RoofSpanSetup bundle"
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

# 6) Release metadata + SHA256SUMS describing exactly these bytes (written only after full success).
function Get-FileFacts([string]$Path) {
  $item = Get-Item $Path
  $sig = Get-AuthenticodeSignature -FilePath $Path
  [ordered]@{
    name = $item.Name
    size = $item.Length
    sha256 = (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    file_version = $item.VersionInfo.FileVersion
    product_version = $item.VersionInfo.ProductVersion
    signature_status = [string]$sig.Status
    signer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }
  }
}
$updateKey = Join-Path $StageDir "config-templates\update_public_key.pem"
$updateKeyText = if (Test-Path $updateKey) { Get-Content $updateKey -Raw } else { "" }
$updateKeyPlaceholder = (-not $updateKeyText) -or ($updateKeyText -match 'PLACEHOLDER') -or ($updateKeyText -notmatch 'BEGIN PUBLIC KEY')
$artifacts = @($finalSetup, $stableSetup, $finalMsi) | ForEach-Object { Get-FileFacts $_ }
$reasons = @()
if (-not $SignCertThumbprint) { $reasons += "unsigned" }
foreach ($a in $artifacts) { if ($a.signature_status -ne 'Valid') { $reasons += "signature not valid: $($a.name)" } }
if ($updateKeyPlaceholder) { $reasons += "update public key missing or placeholder" }
$metadata = [ordered]@{
  schema = "roofspan-installer-build-v1"
  product = "RoofSpan Office"
  version = $Version
  git_sha = $gitSha
  built_utc = (Get-Date).ToUniversalTime().ToString("o")
  artifacts = $artifacts
  prerequisites = [ordered]@{
    postgresql = Get-FileFacts $PostgresInstaller
    webview2 = Get-FileFacts $WebView2StandaloneInstaller
  }
  upgrade_coordinator = Get-FileFacts $upgradeExe
  service_executables = $servicesManifest.executables
  update_public_key_sha256 = if (Test-Path $updateKey) { (Get-FileHash $updateKey -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
  update_public_key_placeholder = [bool]$updateKeyPlaceholder
  signed = [bool]$SignCertThumbprint
  signing_thumbprint = if ($SignCertThumbprint) { $SignCertThumbprint } else { $null }
  releasable = ($reasons.Count -eq 0)
  not_releasable_reasons = $reasons
}
$metadata | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $OutDir "build-metadata.json")
($artifacts | ForEach-Object { "$($_.sha256)  $($_.name)" }) | Set-Content -Encoding ASCII (Join-Path $OutDir "SHA256SUMS.txt")

# 7) Report the exact release identity so the file under test is unambiguous.
$setupItem = Get-Item $finalSetup
$setupHash = (Get-FileHash $finalSetup -Algorithm SHA256).Hash
$setupMB = [math]::Round($setupItem.Length / 1MB, 2)
Write-Host "==> Artifacts in $OutDir :"
Write-Host "    RoofSpanOffice-$Version.msi"
Write-Host "    RoofSpanSetup-$Version.exe   -> upload to /releases/"
Write-Host "    RoofSpanSetup.exe            -> upload to /latest/"
Write-Host "    build-metadata.json, SHA256SUMS.txt"
if ($UpdateSigningPrivateKey) { Write-Host "    latest.json                  -> upload to /update/windows/" }
Write-Host ""
Write-Host "==> Release identity (verify this exact file is what you test/ship):"
Write-Host "    Version    : $Version"
Write-Host "    Git SHA    : $gitSha"
Write-Host "    Artifact   : RoofSpanSetup-$Version.exe"
Write-Host "    Size       : $($setupItem.Length) bytes ($setupMB MB)"
Write-Host "    SHA-256    : $setupHash"
Write-Host "    Releasable : $($metadata.releasable) $(if ($reasons) { '(' + ($reasons -join '; ') + ')' })"
Write-Host "HUMAN REQUIRED: upload artifacts to the approved private S3 behind CloudFront."
