# Assembles the RoofSpan Office install staging tree consumed by installer\RoofSpan.wxs.
# HUMAN REQUIRED: run on Windows (PyInstaller + Node/yarn for the one-time frontend build).
#   .\stage.ps1 -StageDir ..\..\_stage
#
# Produces:
#   _stage\services\{roofspan-backend,roofspan-relay-connector,roofspan-update-service}.exe
#   _stage\frontend\**            (production build of /app/frontend - the Office UI ONLY)
#   _stage\runtime\**             (extra runtime assets, e.g. pg_dump for backups)
#   _stage\config-templates\**    (config templates + update_public_key.pem)
param(
  [Parameter(Mandatory=$true)][string]$StageDir,
  [string]$FrontendDir = "..\..\frontend",
  [string]$UpdatePublicKey = ""      # path to the update-verification PUBLIC key (HUMAN provides)
)
$ErrorActionPreference = "Stop"

# ---- Normalize ALL caller-supplied paths to ABSOLUTE up front, BEFORE any Push-Location / child script
# / build / copy. GetFullPath works even when the target dir does not yet exist. This prevents a relative
# $StageDir (e.g. ..\..\_stage) from re-resolving against a different CWD after Push-Location and splitting
# the stage tree into a stray parent-directory _stage.
function Resolve-AbsPath([string]$p) {
  if ([System.IO.Path]::IsPathRooted($p)) { return [System.IO.Path]::GetFullPath($p) }
  return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $p))
}
$stageRoot = Resolve-AbsPath $StageDir
# FrontendDir is documented relative to the installer script dir; resolve it against $PSScriptRoot.
$feDirResolved = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $FrontendDir))

# ---- FAIL-FAST: frontend toolchain + lockfiles must exist before any expensive work.
if (-not (Get-Command yarn -ErrorAction SilentlyContinue)) {
  throw "yarn not found. Install Node.js LTS + 'corepack enable' (or npm i -g yarn)."
}
if (-not (Test-Path (Join-Path $feDirResolved "package.json"))) { throw "frontend package.json not found at '$feDirResolved'." }
if (-not (Test-Path (Join-Path $feDirResolved "yarn.lock")))    { throw "frontend yarn.lock not found at '$feDirResolved'." }

# All stage destinations are absolute (rooted under $stageRoot) and never change meaning after Push-Location.
$services = Join-Path $stageRoot "services"
$frontend = Join-Path $stageRoot "frontend"
$runtime  = Join-Path $stageRoot "runtime"
$config   = Join-Path $stageRoot "config-templates"
$null = New-Item -ItemType Directory -Force -Path $stageRoot,$services,$frontend,$runtime,$config

# 1) Service executables (PyInstaller).
& (Join-Path $PSScriptRoot "..\winbuild\build_exes.ps1") -OutDir $services

# 2) Office frontend production build (Office UI ONLY - never roofspan-website).
Push-Location $feDirResolved
try {
  # Always synchronize deps against the committed lockfile so a git pull that changed
  # dependencies is buildable immediately (do NOT rely on node_modules existing).
  yarn install --frozen-lockfile
  yarn build
  if (-not (Test-Path ".\build\index.html")) { throw "frontend build did not produce build\index.html" }
  # $frontend is absolute, so this copies to $stageRoot\frontend regardless of the current directory.
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

# ---- FAIL-FAST: the COMPLETE stage tree that build.ps1 consumes must exist before declaring success.
$requiredStage = @(
  (Join-Path $services "roofspan-backend.exe"),
  (Join-Path $services "roofspan-relay-connector.exe"),
  (Join-Path $services "roofspan-update-service.exe"),
  (Join-Path $frontend "index.html"),
  $runtime,
  $config
)
foreach ($p in $requiredStage) {
  if (-not (Test-Path $p)) { throw "Stage incomplete - missing '$p'. Staging did NOT complete." }
}

Write-Host "==> Stage assembled at $stageRoot"
