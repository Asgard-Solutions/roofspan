# Assembles the RoofSpan Office install staging tree consumed by installer\RoofSpan.wxs.
# HUMAN REQUIRED: run on Windows (PyInstaller + Node/yarn for the one-time frontend build).
#   .\stage.ps1 -StageDir ..\..\_stage
#
# Produces:
#   _stage\services\{roofspan-backend,roofspan-relay-connector,roofspan-update-service}.exe
#   _stage\frontend\**            (production build of /app/frontend — the Office UI ONLY)
#   _stage\runtime\**             (extra runtime assets, e.g. pg_dump for backups)
#   _stage\config-templates\**    (config templates + update_public_key.pem)
param(
  [Parameter(Mandatory=$true)][string]$StageDir,
  [string]$FrontendDir = "..\..\frontend",
  [string]$UpdatePublicKey = ""      # path to the update-verification PUBLIC key (HUMAN provides)
)
$ErrorActionPreference = "Stop"

$services = Join-Path $StageDir "services"
$frontend = Join-Path $StageDir "frontend"
$runtime  = Join-Path $StageDir "runtime"
$config   = Join-Path $StageDir "config-templates"
$null = New-Item -ItemType Directory -Force -Path $StageDir,$services,$frontend,$runtime,$config

# 1) Service executables (PyInstaller).
& (Join-Path $PSScriptRoot "..\winbuild\build_exes.ps1") -OutDir $services

# 2) Office frontend production build (Office UI ONLY — never roofspan-website).
Push-Location $FrontendDir
try {
  if (-not (Test-Path ".\node_modules")) { yarn install --frozen-lockfile }
  yarn build
  if (-not (Test-Path ".\build\index.html")) { throw "frontend build did not produce build\index.html" }
  Copy-Item ".\build\*" $frontend -Recurse -Force
} finally { Pop-Location }

# 3) Config templates + update PUBLIC key (public only).
Copy-Item (Join-Path $PSScriptRoot "..\winbuild\config\*") $config -Recurse -Force
if ($UpdatePublicKey) {
  Copy-Item $UpdatePublicKey (Join-Path $config "update_public_key.pem") -Force
} else {
  Write-Warning "No -UpdatePublicKey supplied; update verification key must be staged before release."
}

# 4) Runtime marker (bundle pg client tools here if needed for pg_dump-based backups).
Set-Content -Path (Join-Path $runtime "README.txt") -Value "RoofSpan Office runtime assets (e.g. pg_dump for pre-update backups)."

Write-Host "==> Stage assembled at $StageDir"
