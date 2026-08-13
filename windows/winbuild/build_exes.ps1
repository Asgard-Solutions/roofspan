# Builds the three RoofSpan Office service executables with PyInstaller.
# HUMAN REQUIRED: run on Windows with the backend requirements + Windows build deps installed:
#   pip install -r ..\..\backend\requirements.txt
#   pip install -r requirements-windows.txt   # pywin32 (SCM service host) + pyinstaller
#   .\build_exes.ps1 -OutDir ..\..\_stage\services
param(
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
  throw "pyinstaller not found. Run: pip install -r requirements-windows.txt (and backend requirements)."
}
python -c "import win32serviceutil" 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "pywin32 not found. Run: pip install -r requirements-windows.txt (required for the Windows service host)."
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ToolsDir = Join-Path (Split-Path $OutDir -Parent) "tools"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

# service specs -> staged under services\ ; the recovery tool -> staged under tools\ (NOT a service).
$serviceSpecs = @("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec")
$toolSpecs = @("roofspan-owner-recovery.spec", "roofspan-bootstrap.spec")
$distRoot = Join-Path $PSScriptRoot "dist"
foreach ($spec in ($serviceSpecs + $toolSpecs)) {
  $specPath = Join-Path $PSScriptRoot $spec
  if (-not (Test-Path $specPath)) { throw "Missing spec: $specPath" }
  # Clean distpath BEFORE each build so we only ever stage THIS spec's freshly-produced exe (never a
  # leftover exe from a previous spec/build). --clean also drops PyInstaller's analysis cache.
  if (Test-Path $distRoot) { Remove-Item $distRoot -Recurse -Force }
  Write-Host "==> PyInstaller $spec"
  pyinstaller --clean --noconfirm --distpath $distRoot `
              --workpath (Join-Path $PSScriptRoot "build") $specPath
  $dest = if ($toolSpecs -contains $spec) { $ToolsDir } else { $OutDir }
  $produced = Get-ChildItem -Path $distRoot -Filter "*.exe"
  if (-not $produced) { throw "PyInstaller did not produce an exe for $spec" }
  if ($produced.Count -ne 1) { throw "Expected exactly one exe for $spec; got: $($produced.Name -join ', ')" }
  foreach ($p in $produced) { Copy-Item $p.FullName (Join-Path $dest $p.Name) -Force }
}
Write-Host "==> Services staged in $OutDir ; tools staged in $ToolsDir"
