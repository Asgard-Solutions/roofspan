# Assembles the RoofSpan Office install staging tree consumed by installer\RoofSpan.wxs.
# HUMAN REQUIRED: run on Windows (PyInstaller + Node/yarn + .NET SDK).
#   .\stage.ps1 -StageDir ..\..\_stage
#
# Produces:
#   _stage\services\...             (three PyInstaller ONEDIR Windows services)
#   _stage\frontend\**             (production Office UI)
#   _stage\shell\RoofSpanOffice.exe + self-contained .NET/WebView2 host payload
#   _stage\runtime\RoofSpan.ico     (Windows shell icon)
#   _stage\config-templates\**     (config templates + update_public_key.pem)
param(
  [Parameter(Mandatory=$true)][string]$StageDir,
  [string]$FrontendDir = "..\..\frontend",
  [string]$UpdatePublicKey = ""
)
$ErrorActionPreference = "Stop"

function Resolve-AbsPath([string]$p) {
  if ([System.IO.Path]::IsPathRooted($p)) { return [System.IO.Path]::GetFullPath($p) }
  return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $p))
}

$stageRoot = Resolve-AbsPath $StageDir
$feDirResolved = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $FrontendDir))
$shellProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\shell\RoofSpanOfficeShell.csproj"))

if (-not (Get-Command yarn -ErrorAction SilentlyContinue)) {
  throw "yarn not found. Install Node.js LTS + 'corepack enable' (or npm i -g yarn)."
}
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
  throw ".NET SDK not found. RoofSpan's native Windows shell must be built with dotnet publish."
}
if (-not (Test-Path (Join-Path $feDirResolved "package.json"))) { throw "frontend package.json not found at '$feDirResolved'." }
if (-not (Test-Path (Join-Path $feDirResolved "yarn.lock")))    { throw "frontend yarn.lock not found at '$feDirResolved'." }
if (-not (Test-Path $shellProject)) { throw "RoofSpan Windows shell project not found at '$shellProject'." }

$services = Join-Path $stageRoot "services"
$frontend = Join-Path $stageRoot "frontend"
$shell    = Join-Path $stageRoot "shell"
$runtime  = Join-Path $stageRoot "runtime"
$config   = Join-Path $stageRoot "config-templates"

if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
$null = New-Item -ItemType Directory -Force -Path $stageRoot,$services,$frontend,$shell,$runtime,$config

# 1) Windows services.
& (Join-Path $PSScriptRoot "..\winbuild\build_exes.ps1") -OutDir $services
if ($LASTEXITCODE -ne 0) { throw "RoofSpan service executable build failed." }

# 2) Office frontend production build.
Push-Location $feDirResolved
try {
  yarn install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw "yarn install failed." }
  yarn build
  if ($LASTEXITCODE -ne 0) { throw "frontend yarn build failed." }
  if (-not (Test-Path ".\build\index.html")) { throw "frontend build did not produce build\index.html" }
  Copy-Item ".\build\*" $frontend -Recurse -Force
} finally { Pop-Location }

# 3) Native desktop shell. This is a self-contained WinForms + WebView2 host. The customer sees a normal
# RoofSpan Office application window; the local HTTP endpoint stays an internal implementation detail.
Write-Host "==> Building native RoofSpan Office desktop shell"
dotnet publish $shellProject -c Release -r win-x64 --self-contained true -o $shell `
  -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false
if ($LASTEXITCODE -ne 0) { throw "RoofSpan native desktop shell build failed." }
if (-not (Test-Path (Join-Path $shell "RoofSpanOffice.exe"))) {
  throw "RoofSpan native desktop shell did not produce shell\RoofSpanOffice.exe."
}

# 4) Build the Windows icon from the canonical RoofSpan app icon.
$brandPng = Join-Path $feDirResolved "public\brand\roofspan-appicon.png"
$roofspanIco = Join-Path $runtime "RoofSpan.ico"
if (-not (Test-Path $brandPng)) { throw "RoofSpan app icon not found at '$brandPng'." }
Add-Type -AssemblyName System.Drawing
$srcImage = [System.Drawing.Image]::FromFile($brandPng)
try {
  $bitmap = New-Object System.Drawing.Bitmap 256,256
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.DrawImage($srcImage, 0, 0, 256, 256)
    } finally { $graphics.Dispose() }
    $iconHandle = $bitmap.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($iconHandle)
    $stream = [System.IO.File]::Create($roofspanIco)
    try { $icon.Save($stream) } finally { $stream.Dispose(); $icon.Dispose() }
  } finally { $bitmap.Dispose() }
} finally { $srcImage.Dispose() }
if (-not (Test-Path $roofspanIco)) { throw "Failed to generate RoofSpan.ico for Windows shell integration." }

# 5) Config templates + update PUBLIC key.
Copy-Item (Join-Path $PSScriptRoot "..\winbuild\config\*") $config -Recurse -Force
if ($UpdatePublicKey) {
  Copy-Item $UpdatePublicKey (Join-Path $config "update_public_key.pem") -Force
} else {
  Write-Warning "No -UpdatePublicKey supplied; update verification key must be staged before release."
}

Set-Content -Path (Join-Path $runtime "README.txt") -Value "RoofSpan Office runtime assets (application icon and backup tools)."

$requiredStage = @(
  (Join-Path $services "roofspan-backend\roofspan-backend.exe"),
  (Join-Path $services "roofspan-relay-connector\roofspan-relay-connector.exe"),
  (Join-Path $services "roofspan-update-service\roofspan-update-service.exe"),
  (Join-Path $frontend "index.html"),
  (Join-Path $shell "RoofSpanOffice.exe"),
  (Join-Path $runtime "RoofSpan.ico"),
  $config
)
foreach ($p in $requiredStage) {
  if (-not (Test-Path $p)) { throw "Stage incomplete - missing '$p'. Staging did NOT complete." }
}

Write-Host "==> Stage assembled at $stageRoot"
