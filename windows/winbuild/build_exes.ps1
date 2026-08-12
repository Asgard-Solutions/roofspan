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

$specs = @("roofspan-backend.spec", "roofspan-relay-connector.spec", "roofspan-update-service.spec")
foreach ($spec in $specs) {
  $specPath = Join-Path $PSScriptRoot $spec
  if (-not (Test-Path $specPath)) { throw "Missing spec: $specPath" }
  Write-Host "==> PyInstaller $spec"
  pyinstaller --clean --noconfirm --distpath (Join-Path $PSScriptRoot "dist") `
              --workpath (Join-Path $PSScriptRoot "build") $specPath
  $name = [System.IO.Path]::GetFileNameWithoutExtension($spec)
  $exe = Join-Path $PSScriptRoot "dist\$name.exe"
  if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }
  Copy-Item $exe (Join-Path $OutDir "$name.exe") -Force
}
Write-Host "==> Service executables staged in $OutDir"
