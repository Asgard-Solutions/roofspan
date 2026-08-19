# Builds the RoofSpan Office service/tool executables with PyInstaller.
# HUMAN REQUIRED: run on Windows. NO manual venv activation needed - this script resolves (and, if missing
# or incomplete, creates/repairs) the canonical <repo-root>\.venv and installs backend + Windows build
# requirements automatically. See winbuild\python_env.ps1.
#   .\build_exes.ps1 -OutDir ..\..\_stage\services
param(
  [Parameter(Mandatory=$true)][string]$OutDir
)
$ErrorActionPreference = "Stop"

# Resolve (creating/repairing if necessary) the canonical <repo-root>\.venv interpreter. All PyInstaller
# invocations below go through THIS interpreter - never a PATH-resolved / globally-installed PyInstaller.
. (Join-Path $PSScriptRoot "python_env.ps1")
$VenvPython = Get-RoofSpanBuildPython

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ToolsDir = Join-Path (Split-Path $OutDir -Parent) "tools"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

# service specs -> staged under services\ ; the recovery tool -> staged under tools\ (NOT a service).
# NOTE: RoofSpanOffice.exe (the WebView2 desktop shell) is a .NET build, NOT PyInstaller - it is produced
# by windows\desktop\build_shell.ps1 (invoked from installer\stage.ps1) and staged into tools\ separately.
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
  & $VenvPython -m PyInstaller --clean --noconfirm --distpath $distRoot `
              --workpath (Join-Path $PSScriptRoot "build") $specPath
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $spec (exit code $LASTEXITCODE)." }
  $dest = if ($toolSpecs -contains $spec) { $ToolsDir } else { $OutDir }
  $produced = Get-ChildItem -Path $distRoot -Filter "*.exe"
  if (-not $produced) { throw "PyInstaller did not produce an exe for $spec" }
  if ($produced.Count -ne 1) { throw "Expected exactly one exe for $spec; got: $($produced.Name -join ', ')" }
  foreach ($p in $produced) { Copy-Item $p.FullName (Join-Path $dest $p.Name) -Force }
}
Write-Host "==> Services staged in $OutDir ; tools staged in $ToolsDir"
