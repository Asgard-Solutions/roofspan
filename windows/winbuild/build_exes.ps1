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
$preflight = "import sys; sys.path.insert(0, r'$backend'); import server, property_dedup, location_upgrade, mapbox_geocoding, maptiler, mapbox_vector_tile, shapely; import control_plane.migrations_runner; print('backend import preflight OK')"
& $python -c $preflight
if ($LASTEXITCODE -ne 0) { throw "Backend runtime import preflight failed; refusing to build installer." }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

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

  # The embedded Control Plane migration runner resolves its files from
  # _internal\control_plane at runtime. Make a missing migration payload a BUILD failure rather than
  # shipping an Office build that starts normally but returns 500/502 from Mobile Access.
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
Write-Host "==> Service executables (onedir) staged in $OutDir"
