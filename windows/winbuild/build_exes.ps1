# Builds the three RoofSpan Office service executables with PyInstaller.
# HUMAN REQUIRED: run on Windows with `pip install pyinstaller` and the backend requirements installed.
#   .\build_exes.ps1 -OutDir ..\..\_stage\services
param(
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference = "Stop"

# Repo root is two levels up from windows\winbuild.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$backend = Join-Path $repoRoot "backend"

# ---- FAIL-FAST: backend Alembic assets that the spec packages must exist.
if (-not (Test-Path (Join-Path $backend "alembic")))     { throw "backend\alembic directory not found at '$backend'." }
if (-not (Test-Path (Join-Path $backend "alembic.ini"))) { throw "backend\alembic.ini not found at '$backend'." }

# Prefer the repository-local virtualenv PyInstaller so the user does NOT have to activate .venv.
$venvPyi = Join-Path $repoRoot ".venv\Scripts\pyinstaller.exe"
if (Test-Path $venvPyi) {
  $pyinstaller = $venvPyi
} elseif (Get-Command pyinstaller -ErrorAction SilentlyContinue) {
  $pyinstaller = "pyinstaller"
} else {
  throw "PyInstaller not found. Create the repo venv (py -m venv .venv; .\.venv\Scripts\pip install -r backend\requirements.txt pyinstaller) or 'pip install pyinstaller'."
}
Write-Host "==> Using PyInstaller: $pyinstaller"

# ---- Ensure pywin32 is present in the SAME environment PyInstaller freezes from (required so the
# frozen service exes can host the Windows Service Control dispatcher). pywin32 is Windows-only and is
# intentionally NOT in backend/requirements.txt (that installs on Linux/CI too).
if (Test-Path $venvPyi) {
  $pip = Join-Path $repoRoot ".venv\Scripts\pip.exe"
} else {
  $pip = "pip"
}
& $pip show pywin32 *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "==> Installing pywin32 (Windows service runtime) into the build environment"
  & $pip install pywin32
  if ($LASTEXITCODE -ne 0) { throw "Failed to install pywin32; the Windows services cannot be built." }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$specs = @("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec")
foreach ($spec in $specs) {
  $specPath = Join-Path $PSScriptRoot $spec
  if (-not (Test-Path $specPath)) { throw "Missing spec: $specPath" }
  Write-Host "==> PyInstaller $spec"
  & $pyinstaller --clean --noconfirm --distpath (Join-Path $PSScriptRoot "dist") `
              --workpath (Join-Path $PSScriptRoot "build") $specPath
  $name = [System.IO.Path]::GetFileNameWithoutExtension($spec)
  # ONEDIR: PyInstaller emits dist\<name>\<name>.exe + dist\<name>\_internal\. Stage the WHOLE folder
  # so the SCM-launched exe finds its dependencies regardless of the working directory.
  $distDir = Join-Path $PSScriptRoot "dist\$name"
  $exe = Join-Path $distDir "$name.exe"
  if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }
  $destDir = Join-Path $OutDir $name
  if (Test-Path $destDir) { Remove-Item $destDir -Recurse -Force }
  Copy-Item $distDir $destDir -Recurse -Force
  if (-not (Test-Path (Join-Path $destDir "$name.exe"))) { throw "Staging did not place $name.exe under $destDir" }
}
Write-Host "==> Service executables (onedir) staged in $OutDir"
