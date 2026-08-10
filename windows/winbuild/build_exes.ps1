# Builds the three RoofSpan Office service executables with PyInstaller.
# HUMAN REQUIRED: run on Windows with `pip install pyinstaller` and the backend requirements installed.
#   .\build_exes.ps1 -OutDir ..\..\_stage\services
param(
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
  throw "pyinstaller not found. Run: pip install pyinstaller (and install backend requirements)."
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
