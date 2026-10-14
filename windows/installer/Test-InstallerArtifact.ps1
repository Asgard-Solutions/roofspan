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
wix burn extract (Join-Path $iso $setupName) -out $ac -outba $ba
Assert-That ($LASTEXITCODE -eq 0) "wix burn extract failed (exit $LASTEXITCODE)"
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
$relay = Get-ChildItem $adminDir -Recurse -Filter "roofspan-relay-connector.exe" | Select-Object -First 1
Assert-That ($null -ne $relay) "packaged roofspan-relay-connector.exe not found in the MSI"
$infoLine = @(& $relay.FullName --build-info) | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
Assert-That ($LASTEXITCODE -eq 0 -and $infoLine) "packaged Relay connector --build-info failed"
$info = $infoLine | ConvertFrom-Json
Assert-That ($info.build_sha -eq $ExpectedGitSha) "packaged build SHA '$($info.build_sha)' != '$ExpectedGitSha'"
Assert-That ($info.version -eq $ExpectedVersion) "packaged version '$($info.version)' != '$ExpectedVersion'"

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
  releasable = ($reasons.Count -eq 0)
  not_releasable_reasons = $reasons
}
$result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $DistDir "artifact-verification.json")
Write-Host "OK: artifact verified - version $ExpectedVersion, git $($info.build_sha), RoofSpanSetup SHA-256 $setupSha"
Write-Host "    PostgreSQL payload $($prereqs.postgresql.name) sha256=$($prereqs.postgresql.sha256)"
Write-Host "    WebView2 payload  $($prereqs.webview2.name) sha256=$($prereqs.webview2.sha256) version=$($prereqs.webview2.product_version)"
Write-Host "    Releasable: $($result.releasable) $(if ($reasons) { '(' + ($reasons -join '; ') + ')' })"
