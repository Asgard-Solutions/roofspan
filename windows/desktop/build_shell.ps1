# Builds RoofSpanOffice.exe (the WebView2 desktop shell, .NET WinForms) and stages it under tools\.
# HUMAN REQUIRED: run on Windows with the .NET 10 SDK installed (https://dotnet.microsoft.com/download).
# This is invoked AUTOMATICALLY by installer\stage.ps1 - there is no separate manual build step to remember.
#
# Produces a single self-contained exe (win-x64) so WiX packages exactly one file: tools\RoofSpanOffice.exe.
param(
  [Parameter(Mandatory=$true)][string]$ToolsDir
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
  throw "dotnet CLI not found. Install the .NET 10 SDK (https://dotnet.microsoft.com/download) to build the RoofSpan Office desktop shell."
}

$proj = Join-Path $PSScriptRoot "RoofSpanOffice\RoofSpanOffice.csproj"
if (-not (Test-Path $proj)) { throw "Missing project: $proj" }

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
$ToolsDir = (Resolve-Path -LiteralPath $ToolsDir).Path

$publishDir = Join-Path $PSScriptRoot "publish"
# Clean the publish output FIRST so a stale exe from a previous build can never be staged as if fresh.
if (Test-Path $publishDir) { Remove-Item $publishDir -Recurse -Force }
$buildStart = (Get-Date).ToUniversalTime()

Write-Host "==> dotnet publish RoofSpanOffice.exe (WebView2 desktop shell, single-file self-contained win-x64)"
dotnet publish $proj -c Release -r win-x64 --self-contained true -o $publishDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed (exit code $LASTEXITCODE)." }

$exe = Join-Path $publishDir "RoofSpanOffice.exe"
if (-not (Test-Path $exe)) { throw "dotnet publish did not produce RoofSpanOffice.exe." }
# Fail closed on a stale artifact (must be produced by THIS invocation).
if ((Get-Item $exe).LastWriteTimeUtc -lt $buildStart) {
  throw "RoofSpanOffice.exe is stale (not produced by this build). Aborting."
}

Copy-Item $exe (Join-Path $ToolsDir "RoofSpanOffice.exe") -Force
Write-Host "==> Staged RoofSpanOffice.exe -> $ToolsDir"
