# Builds RoofSpanBaFunctions.dll (WiX v5 BAFunctions native hook) reproducibly. HUMAN REQUIRED: Windows +
# Visual Studio 2022 Desktop C++ (MSBuild). Restores the PINNED WiX v5 native SDK, compiles, and prints the
# absolute path of the produced DLL (last line of stdout) so installer\build.ps1 can consume it.
#
#   .\build_bafunctions.ps1 [-Configuration Release] [-Platform x64]
param(
  [string]$Configuration = "Release",
  [string]$Platform = "x64"
)
$ErrorActionPreference = "Stop"

$proj = Join-Path $PSScriptRoot "RoofSpanBaFunctions.vcxproj"
if (-not (Test-Path $proj)) { throw "Missing project: $proj" }

$msbuild = Get-Command msbuild -ErrorAction SilentlyContinue
if (-not $msbuild) {
  throw "MSBuild not found. Open a 'Developer PowerShell for VS 2022' or install VS 2022 Desktop C++ workload."
}

# Restore pinned WiX v5 native NuGet packages, then build.
& msbuild $proj /t:Restore /p:Configuration=$Configuration /p:Platform=$Platform /nologo /v:minimal
if ($LASTEXITCODE -ne 0) { throw "NuGet restore failed for $proj." }
& msbuild $proj /t:Build /p:Configuration=$Configuration /p:Platform=$Platform /nologo /v:minimal
if ($LASTEXITCODE -ne 0) { throw "BAFunctions build failed for $proj." }

$dll = Join-Path $PSScriptRoot "bin\$Platform\$Configuration\RoofSpanBaFunctions.dll"
if (-not (Test-Path $dll)) { throw "BAFunctions build did not produce '$dll'." }

Write-Host "==> Built BAFunctions: $dll"
# IMPORTANT: keep this the LAST line so callers can capture it with Select-Object -Last 1.
Write-Output (Resolve-Path $dll).Path
