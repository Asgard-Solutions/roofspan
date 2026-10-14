# Service-executable provenance shared by winbuild\build_exes.ps1 (writer) and installer\build.ps1 (verifier).
# The list below must equal winbuild\targets.py SERVICE_TARGETS (enforced by windows/tests).
$ErrorActionPreference = "Stop"

$script:RequiredServices = @("roofspan-backend", "roofspan-relay-connector", "roofspan-update-service", "roofspan-update-broker")
$script:ManifestName = "services-build-manifest.json"
$script:ManifestSchema = "roofspan-services-build-v1"

function Get-RoofSpanRequiredServices { return ,@($script:RequiredServices) }

function Get-ServicesBuildManifestPath([string]$ServicesDir) { return (Join-Path $ServicesDir $script:ManifestName) }

function Get-ServiceExeSha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

# Fails the build unless EVERY required service was built in this run and is present in $OutDir.
function Write-ServicesBuildManifest {
  param([Parameter(Mandatory=$true)][string]$OutDir, [Parameter(Mandatory=$true)][string]$Version,
        [Parameter(Mandatory=$true)][string]$GitSha, [Parameter(Mandatory=$true)][System.Collections.IDictionary]$BuiltHashes)
  $exes = [ordered]@{}
  foreach ($svc in $script:RequiredServices) {
    $exe = Join-Path $OutDir "$svc\$svc.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf) -or -not $BuiltHashes.Contains($svc)) {
      throw "Required service executable missing after build: $exe. Packaging must not start."
    }
    $sha = Get-ServiceExeSha256 $exe
    if ($sha -ne $BuiltHashes[$svc]) { throw "Staged $svc.exe ($sha) is not the executable PyInstaller just built ($($BuiltHashes[$svc]))." }
    $exes[$svc] = [ordered]@{ path = "$svc\$svc.exe"; sha256 = $sha; size = (Get-Item -LiteralPath $exe).Length }
  }
  $path = Get-ServicesBuildManifestPath $OutDir
  [ordered]@{ schema = $script:ManifestSchema; version = $Version; git_sha = $GitSha; executables = $exes } |
    ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $path
  return $path
}

# Packaging gate: the staged executables must be byte-identical to what build_exes.ps1 produced for this source.
function Assert-ServicesBuildManifest {
  param([Parameter(Mandatory=$true)][string]$ServicesDir, [Parameter(Mandatory=$true)][string]$Version,
        [Parameter(Mandatory=$true)][string]$GitSha)
  $path = Get-ServicesBuildManifestPath $ServicesDir
  if (-not (Test-Path -LiteralPath $path)) { throw "Staging incomplete - missing '$path'. Run installer\stage.ps1 first." }
  $m = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  if ($m.schema -ne $script:ManifestSchema -or $m.git_sha -ne $GitSha -or $m.version -ne $Version) {
    throw "Services build manifest is stale (SHA=$($m.git_sha) version=$($m.version); expected $GitSha $Version). Remove _stage and run stage.ps1 again."
  }
  $names = @($m.executables.PSObject.Properties.Name | Sort-Object)
  if (($names -join ",") -ne (@($script:RequiredServices | Sort-Object) -join ",")) {
    throw "Services build manifest lists [$($names -join ', ')]; expected [$($script:RequiredServices -join ', ')]."
  }
  foreach ($svc in $script:RequiredServices) {
    $exe = Join-Path $ServicesDir "$svc\$svc.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Staging incomplete - missing '$exe'. Run installer\stage.ps1 first." }
    $actual = Get-ServiceExeSha256 $exe
    $expected = $m.executables.$svc.sha256
    if ($actual -ne $expected) { throw "Staged $svc.exe ($actual) is not the executable built by build_exes.ps1 ($expected); refusing to package it." }
    Write-Host "==> Verified staged $svc.exe is the built executable (SHA-256 $actual)"
  }
  return $m
}

Export-ModuleMember -Function Get-RoofSpanRequiredServices, Get-ServicesBuildManifestPath, Get-ServiceExeSha256,
  Write-ServicesBuildManifest, Assert-ServicesBuildManifest
