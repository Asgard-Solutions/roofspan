# Builds the three RoofSpan Office service executables with PyInstaller.
# HUMAN REQUIRED: run on Windows with `pip install pyinstaller` available in the repo venv or PATH.
#   .\build_exes.ps1 -OutDir ..\..\_stage\services
param(
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference = "Stop"

# Repo root is two levels up from windows\winbuild.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$backend = Join-Path $repoRoot "backend"
$alembicDir = Join-Path $backend "alembic"
$cpAlembicDir = Join-Path $backend "control_plane\alembic"
$cpAlembicIni = Join-Path $backend "control_plane\alembic.ini"
$requirements = Join-Path $backend "requirements.txt"

if (-not (Test-Path $alembicDir))                         { throw "backend\alembic directory not found at '$backend'." }
if (-not (Test-Path (Join-Path $backend "alembic.ini"))) { throw "backend\alembic.ini not found at '$backend'." }
if (-not (Test-Path $cpAlembicDir))                       { throw "backend\control_plane\alembic directory not found at '$backend'." }
if (-not (Test-Path $cpAlembicIni))                       { throw "backend\control_plane\alembic.ini not found at '$backend'." }
if (-not (Test-Path $requirements))                       { throw "backend\requirements.txt not found at '$requirements'." }

# Remove stale migration bytecode before freezing either Alembic tree.
foreach ($migrationDir in @($alembicDir, $cpAlembicDir)) {
  Get-ChildItem -Path $migrationDir -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
  Get-ChildItem -Path $migrationDir -File -Include *.pyc,*.pyo -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Force
}
foreach ($cleanDir in @((Join-Path $PSScriptRoot "dist"), (Join-Path $PSScriptRoot "build"))) {
  if (Test-Path $cleanDir) { Remove-Item $cleanDir -Recurse -Force }
}
foreach ($migrationDir in @($alembicDir, $cpAlembicDir)) {
  $staleBytecode = Get-ChildItem -Path $migrationDir -File -Include *.pyc,*.pyo -Recurse -ErrorAction SilentlyContinue
  if ($staleBytecode) { throw "Stale Alembic bytecode remains after cleanup under '$migrationDir'; refusing to freeze service executables." }
}

$venvPyi = Join-Path $repoRoot ".venv\Scripts\pyinstaller.exe"
if (Test-Path $venvPyi) {
  $pyinstaller = $venvPyi
  $pip = Join-Path $repoRoot ".venv\Scripts\pip.exe"
  $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
} elseif (Get-Command pyinstaller -ErrorAction SilentlyContinue) {
  $pyinstaller = "pyinstaller"
  $pip = "pip"
  $python = "python"
} else {
  throw "PyInstaller not found. Create the repo venv (py -m venv .venv; .\.venv\Scripts\pip install pyinstaller) or install PyInstaller on PATH."
}
Write-Host "==> Using PyInstaller: $pyinstaller"

Write-Host "==> Syncing backend Python dependencies"
& $pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Failed to install backend requirements; refusing to freeze stale dependencies." }

& $pip show pywin32 *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "==> Installing pywin32 (Windows service runtime) into the build environment"
  & $pip install pywin32
  if ($LASTEXITCODE -ne 0) { throw "Failed to install pywin32; the Windows services cannot be built." }
}

Write-Host "==> Verifying backend runtime imports"
$preflight = "import sys; sys.path.insert(0, r'$backend'); import server, property_dedup, location_upgrade, mapbox_geocoding, maptiler, mapbox_vector_tile, shapely; import control_plane.bootstrap, control_plane.readiness, control_plane.migrations_runner; print('backend import preflight OK')"
& $python -c $preflight
if ($LASTEXITCODE -ne 0) { throw "Backend runtime import preflight failed; refusing to build installer." }

# Freeze the exact Git revision into the backend process as a PyInstaller runtime hook. This gives
# support a deterministic build SHA through /api/version and backend-service.log on customer machines.
$gitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $gitSha -notmatch '^[0-9a-fA-F]{40}$') {
  throw "Unable to resolve the source Git SHA; refusing to produce an untraceable Office build."
}
$buildWork = Join-Path $PSScriptRoot "build"
New-Item -ItemType Directory -Force -Path $buildWork | Out-Null
$buildInfoHook = Join-Path $PSScriptRoot "roofspan_build_info_hook.generated.py"
$hookText = @"
import os
os.environ['ROOFSPAN_BUILD_SHA'] = '$gitSha'
os.environ.setdefault('CP_DEV_SIGNING_KEYS_DIR', r'C:\ProgramData\RoofSpan\identity\cp-signing-keys')
"@
Set-Content -Path $buildInfoHook -Value $hookText -Encoding ASCII
$env:ROOFSPAN_BUILD_INFO_HOOK = $buildInfoHook
Write-Host "==> Embedding source Git SHA: $gitSha"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

try {
  $specs = @("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec")
  foreach ($spec in $specs) {
    $specPath = Join-Path $PSScriptRoot $spec
    if (-not (Test-Path $specPath)) { throw "Missing spec: $specPath" }
    Write-Host "==> PyInstaller $spec"
    & $pyinstaller --clean --noconfirm --distpath (Join-Path $PSScriptRoot "dist") `
                --workpath (Join-Path $PSScriptRoot "build") $specPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $spec (exit $LASTEXITCODE)." }
    $name = [System.IO.Path]::GetFileNameWithoutExtension($spec)
    $distDir = Join-Path $PSScriptRoot "dist\$name"
    $exe = Join-Path $distDir "$name.exe"
    if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }

    if ($name -eq "roofspan-backend") {
      $internalDir = Join-Path $distDir "_internal"
      $requiredBackendAssets = @(
        "alembic.ini",
        "alembic\env.py",
        "control_plane\alembic.ini",
        "control_plane\alembic\env.py"
      )
      foreach ($relativeAsset in $requiredBackendAssets) {
        $assetPath = Join-Path $internalDir $relativeAsset
        if (-not (Test-Path $assetPath)) {
          throw "PyInstaller backend payload is missing required migration asset '$relativeAsset' at '$assetPath'."
        }
      }
      $cpVersions = Join-Path $internalDir "control_plane\alembic\versions"
      if (-not (Test-Path $cpVersions)) {
        throw "PyInstaller backend payload is missing Control Plane Alembic versions at '$cpVersions'."
      }
      if (-not (Get-ChildItem -Path $cpVersions -File -Filter "*.py" -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "PyInstaller backend payload contains no Control Plane Alembic version files at '$cpVersions'."
      }
      Write-Host "==> Verified business + Control Plane Alembic assets in frozen backend"
    }

    $destDir = Join-Path $OutDir $name
    if (Test-Path $destDir) { Remove-Item $destDir -Recurse -Force }
    Copy-Item $distDir $destDir -Recurse -Force
    if (-not (Test-Path (Join-Path $destDir "$name.exe"))) { throw "Staging did not place $name.exe under $destDir" }
  }
} finally {
  Remove-Item Env:\ROOFSPAN_BUILD_INFO_HOOK -ErrorAction SilentlyContinue
  Remove-Item $buildInfoHook -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Service executables (onedir) staged in $OutDir"
