<#
  Independently verifies a built RoofSpan Office release folder (output of build.ps1) WITHOUT rebuilding.
  Windows only (wix CLI, msiexec, WindowsInstaller COM). Fails (throws) on any mismatch:

    - SHA256SUMS.txt and build-metadata.json match the actual bytes; RoofSpanSetup.exe == RoofSpanSetup-<ver>.exe
    - the bundle's embedded payloads include byte-identical copies of the Office MSI and both prerequisites
    - bundle version resource, MSI ProductVersion and MSI UpgradeCode match windows\VERSION / constants.wxi
    - the packaged Relay connector reports the expected Git SHA and version (--build-info)

  Writes artifact-verification.json next to the artifacts. "releasable" additionally requires valid
  Authenticode signatures and a real (non-placeholder) update public key.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$DistDir,
  [Parameter(Mandatory=$true)][string]$ExpectedGitSha,
  [Parameter(Mandatory=$true)][string]$ExpectedVersion,
  [string]$WorkDir = (Join-Path ([System.IO.Path]::GetTempPath()) "roofspan-artifact-verify")
)
$ErrorActionPreference = "Stop"

function Get-Sha([string]$Path) { (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Assert-That([bool]$Condition, [string]$Message) { if (-not $Condition) { throw "ARTIFACT VERIFICATION FAILED: $Message" } }

$DistDir = (Resolve-Path $DistDir).Path
$setupName = "RoofSpanSetup-$ExpectedVersion.exe"
$msiName = "RoofSpanOffice-$ExpectedVersion.msi"
$setup = Join-Path $DistDir $setupName
$stable = Join-Path $DistDir "RoofSpanSetup.exe"
$msi = Join-Path $DistDir $msiName
$metaPath = Join-Path $DistDir "build-metadata.json"
$sumsPath = Join-Path $DistDir "SHA256SUMS.txt"
foreach ($p in @($setup, $stable, $msi, $metaPath, $sumsPath)) { Assert-That (Test-Path $p) "missing $p" }

# 1) Hash report + metadata describe these exact bytes.
$meta = Get-Content $metaPath -Raw | ConvertFrom-Json
Assert-That ($meta.version -eq $ExpectedVersion) "metadata version '$($meta.version)' != '$ExpectedVersion'"
Assert-That ($meta.git_sha -eq $ExpectedGitSha) "metadata git_sha '$($meta.git_sha)' != '$ExpectedGitSha'"
$sums = @{}
foreach ($line in Get-Content $sumsPath) {
  if ($line -match '^([0-9a-f]{64})  (\S+)$') { $sums[$Matches[2]] = $Matches[1] } elseif ($line.Trim()) { throw "ARTIFACT VERIFICATION FAILED: malformed SHA256SUMS line '$line'" }
}
foreach ($name in @($setupName, "RoofSpanSetup.exe", $msiName)) {
  $actual = Get-Sha (Join-Path $DistDir $name)
  Assert-That ($sums[$name] -eq $actual) "SHA256SUMS entry for $name does not match the file"
  $m = @($meta.artifacts | Where-Object { $_.name -eq $name })
  Assert-That ($m.Count -eq 1 -and $m[0].sha256 -eq $actual) "build-metadata entry for $name does not match the file"
}
$setupSha = Get-Sha $setup
Assert-That ($setupSha -eq (Get-Sha $stable)) "RoofSpanSetup.exe is not byte-identical to $setupName"
$msiSha = Get-Sha $msi

# 2) Bundle version resource.
$bundleVersion = (Get-Item $setup).VersionInfo.ProductVersion
Assert-That ("$bundleVersion" -match ('^' + [regex]::Escape($ExpectedVersion) + '(\.0)?$')) "bundle version resource '$bundleVersion' != '$ExpectedVersion'"

# 3) Embedded payloads: extract from an isolated copy and match by content hash (name-agnostic).
if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
$iso = Join-Path $WorkDir "isolated"; $ac = Join-Path $WorkDir "attached"; $ba = Join-Path $WorkDir "ba"
New-Item -ItemType Directory -Force -Path $iso, $ac, $ba | Out-Null
Copy-Item $setup (Join-Path $iso $setupName)
# WiX native CAB extraction can occasionally return Windows ERROR_NO_DATA
# (0x800700e8, 'pipe is being closed') on hosted runners. Retry ONLY that
# transport error with clean output directories. Never skip the subsequent
# byte-for-byte MSI/prerequisite verification, and never retry hash failures.
$extractOk = $false
$extractRc = $null
for ($attempt = 1; $attempt -le 2; $attempt++) {
  if ($attempt -gt 1) {
    Remove-Item -LiteralPath $ac, $ba -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $ac, $ba | Out-Null
  }
  wix burn extract (Join-Path $iso $setupName) -out $ac -outba $ba
  $extractRc = $LASTEXITCODE
  if ($extractRc -eq 0) { $extractOk = $true; break }
  if ($extractRc -ne -2147024664 -or $attempt -eq 2) { break }
  Write-Warning "WiX extraction hit ERROR_NO_DATA (pipe closed); retrying once with clean output directories."
  Start-Sleep -Seconds 10
}
Assert-That $extractOk "wix burn extract failed (exit $extractRc); verified payload hashes were NOT obtained"
$embedded = @{}
Get-ChildItem $ac -Recurse -File | ForEach-Object { $embedded[(Get-Sha $_.FullName)] = $_.Name }
Assert-That ($embedded.ContainsKey($msiSha)) "the bundle does not embed the published Office MSI ($msiName)"
$prereqs = [ordered]@{}
foreach ($k in @("postgresql", "webview2")) {
  $p = $meta.prerequisites.$k
  Assert-That ($null -ne $p -and $p.sha256) "build-metadata has no $k prerequisite"
  Assert-That ($embedded.ContainsKey($p.sha256)) "the bundle does not embed the $k prerequisite recorded in build-metadata ($($p.name))"
  $prereqs[$k] = [ordered]@{ name = $p.name; size = $p.size; sha256 = $p.sha256; product_version = $p.product_version; signer = $p.signer; signature_status = $p.signature_status }
}
# The upgrade coordinator is a bundle payload (not in the MSI): embedded bytes == recorded, identity matches.
$uc = $meta.upgrade_coordinator
Assert-That ($null -ne $uc -and $embedded.ContainsKey($uc.sha256)) "the bundle does not embed the recorded roofspan-upgrade.exe"
$ucPath = (Get-ChildItem $ac -Recurse -File | Where-Object { (Get-Sha $_.FullName) -eq $uc.sha256 } | Select-Object -First 1).FullName
$ucRun = Join-Path $WorkDir "roofspan-upgrade.exe"; Copy-Item $ucPath $ucRun -Force
$ucLine = @(& $ucRun --build-info) | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
$ucInfo = $ucLine | ConvertFrom-Json
Assert-That ($ucInfo.service -eq "roofspan-upgrade" -and $ucInfo.build_sha -eq $ExpectedGitSha -and $ucInfo.version -eq $ExpectedVersion) "embedded roofspan-upgrade.exe identity mismatch: $ucLine"
Assert-That ($ucInfo.fault_injection -ne $true) "embedded roofspan-upgrade.exe is a fault-injection TEST build"
Assert-That ($embedded.ContainsKey($msiSha)) "the coordinator's MSI payload is missing"
$manifestText = (Get-ChildItem $ba -Recurse -Filter *.xml | ForEach-Object { Get-Content $_.FullName -Raw }) -join "`n"
Assert-That ($manifestText -notmatch 'Packaging="external"') "a payload is external (not embedded)"

# 4) MSI properties.
function Get-MsiProperty([string]$Path, [string]$Name) {
  $wi = New-Object -ComObject WindowsInstaller.Installer
  $db = $wi.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $wi, @($Path, 0))
  $view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @("SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Name'"))
  $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
  $rec = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
  $value = if ($rec) { $rec.GetType().InvokeMember("StringData", "GetProperty", $null, $rec, 1) } else { $null }
  $view.GetType().InvokeMember("Close", "InvokeMethod", $null, $view, $null) | Out-Null
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null
  return $value
}
$msiVersion = Get-MsiProperty $msi "ProductVersion"
$msiUpgrade = Get-MsiProperty $msi "UpgradeCode"
Assert-That ($msiVersion -eq $ExpectedVersion) "MSI ProductVersion '$msiVersion' != '$ExpectedVersion'"
$constants = Get-Content (Join-Path $PSScriptRoot "constants.wxi") -Raw
$expectedUpgrade = [regex]::Match($constants, 'RoofSpanUpgradeCode\s*=\s*"([^"]+)"').Groups[1].Value
Assert-That ($msiUpgrade.Trim('{}') -eq $expectedUpgrade.Trim('{}')) "MSI UpgradeCode '$msiUpgrade' != '$expectedUpgrade'"

# 5) Embedded Git SHA + version from the packaged Relay connector (administrative extraction, no install).
$adminDir = Join-Path $WorkDir "msi-admin"
$adminLog = Join-Path $WorkDir "msi-admin.log"
$p = Start-Process msiexec.exe -ArgumentList @("/a", "`"$msi`"", "/qn", "TARGETDIR=`"$adminDir`"", "/L*v", "`"$adminLog`"") -Wait -PassThru
Assert-That ($p.ExitCode -eq 0) "msiexec /a administrative extraction failed (exit $($p.ExitCode)); see $adminLog"
$serviceIdentity = [ordered]@{}
foreach ($svcName in @("roofspan-backend", "roofspan-relay-connector", "roofspan-update-service", "roofspan-update-broker")) {
  $exe = Get-ChildItem $adminDir -Recurse -Filter "$svcName.exe" | Select-Object -First 1
  Assert-That ($null -ne $exe) "packaged $svcName.exe not found in the MSI"
  $packagedHash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $builtHash = $meta.service_executables.$svcName.sha256
  Assert-That ($builtHash -and $packagedHash -eq $builtHash) "packaged $svcName.exe ($packagedHash) is not the executable the build produced ($builtHash)"
  $infoLine = @(& $exe.FullName --build-info) | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
  Assert-That ($LASTEXITCODE -eq 0 -and $infoLine) "packaged $svcName --build-info failed"
  $bi = $infoLine | ConvertFrom-Json
  Assert-That ($bi.service -eq $svcName) "packaged $svcName reports service '$($bi.service)'"
  Assert-That ($bi.build_sha -eq $ExpectedGitSha) "packaged $svcName build SHA '$($bi.build_sha)' != '$ExpectedGitSha'"
  Assert-That ($bi.version -eq $ExpectedVersion) "packaged $svcName version '$($bi.version)' != '$ExpectedVersion'"
  Assert-That ($bi.build_contract -eq "roofspan-build-identity-v1" -and $bi.embedded -eq $true) "packaged $svcName lacks the embedded build identity contract"
  Assert-That ($bi.fault_injection -ne $true) "packaged $svcName is a fault-injection TEST build"
  $serviceIdentity[$svcName] = [ordered]@{ version = $bi.version; build_sha = $bi.build_sha; build_contract = $bi.build_contract }
  if ($svcName -eq "roofspan-relay-connector") { $info = $bi }
}

# 6) Release eligibility (reported, not a verification failure).
$setupSig = Get-AuthenticodeSignature -FilePath $setup
$msiSig = Get-AuthenticodeSignature -FilePath $msi
$reasons = @($meta.not_releasable_reasons)
if ($setupSig.Status -ne 'Valid') { $reasons += "bundle signature: $($setupSig.Status)" }
if ($msiSig.Status -ne 'Valid') { $reasons += "MSI signature: $($msiSig.Status)" }
if ($meta.update_public_key_placeholder) { $reasons += "update public key placeholder" }
$reasons = @($reasons | Where-Object { $_ } | Select-Object -Unique)

$result = [ordered]@{
  schema = "roofspan-installer-verification-v1"
  verified = $true
  version = $ExpectedVersion
  git_sha = $info.build_sha
  bundle_version_resource = $bundleVersion
  msi_product_version = $msiVersion
  msi_upgrade_code = $msiUpgrade
  setup = [ordered]@{ name = $setupName; sha256 = $setupSha; size = (Get-Item $setup).Length; signature_status = [string]$setupSig.Status }
  stable_setup_sha256 = $setupSha
  msi = [ordered]@{ name = $msiName; sha256 = $msiSha; signature_status = [string]$msiSig.Status }
  prerequisites = $prereqs
  service_build_identity = $serviceIdentity
  releasable = ($reasons.Count -eq 0)
  not_releasable_reasons = $reasons
}
$result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $DistDir "artifact-verification.json")
Write-Host "OK: artifact verified - version $ExpectedVersion, git $($info.build_sha), RoofSpanSetup SHA-256 $setupSha"
Write-Host "    PostgreSQL payload $($prereqs.postgresql.name) sha256=$($prereqs.postgresql.sha256)"
Write-Host "    WebView2 payload  $($prereqs.webview2.name) sha256=$($prereqs.webview2.sha256) version=$($prereqs.webview2.product_version)"
Write-Host "    Releasable: $($result.releasable) $(if ($reasons) { '(' + ($reasons -join '; ') + ')' })"
