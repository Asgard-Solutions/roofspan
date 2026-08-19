# Canonical resolution of the RoofSpan Windows *build* Python environment.
#
# Dot-source this file and call Get-RoofSpanBuildPython to obtain a fully-provisioned interpreter path:
#     . (Join-Path $PSScriptRoot "python_env.ps1")
#     $VenvPython = Get-RoofSpanBuildPython
#
# The canonical venv is <repo-root>\.venv (resolved from $PSScriptRoot, NOT the current directory). This
# makes the Windows build runnable from a plain PowerShell session with NO manual `.venv` activation and NO
# dependence on the user's PATH or globally-installed PyInstaller/pywin32. If the venv is missing it is
# created; if it exists but is missing build dependencies it is repaired. All Python build operations must
# go through the returned interpreter (e.g. `& $VenvPython -m PyInstaller ...`).
$ErrorActionPreference = "Stop"

function Get-RoofSpanRepoRoot {
  # windows\winbuild\ -> repo root is two levels up.
  return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}

function Find-BasePython {
  # Locate an interpreter ONLY to create the venv (never used for the build itself). Prefer the Windows
  # 'py' launcher, then python / python3 on PATH.
  $candidates = @(
    @{ Cmd = "py";      Pre = @("-3") },
    @{ Cmd = "python";  Pre = @() },
    @{ Cmd = "python3"; Pre = @() }
  )
  foreach ($c in $candidates) {
    $found = Get-Command $c.Cmd -ErrorAction SilentlyContinue
    if ($found) {
      & $found.Source @($c.Pre + @("--version")) *> $null
      if ($LASTEXITCODE -eq 0) { return @{ Source = $found.Source; Pre = $c.Pre } }
    }
  }
  throw "No Python interpreter found to create the RoofSpan build venv. Install Python 3.10+ (https://www.python.org/downloads/windows/) and re-run."
}

function New-RoofSpanVenv {
  param([Parameter(Mandatory=$true)][string]$VenvDir)
  $base = Find-BasePython
  Write-Host "==> Creating RoofSpan Windows build virtual environment..."
  & $base.Source @($base.Pre + @("-m", "venv", $VenvDir))
  if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment at '$VenvDir'." }
}

function Install-RoofSpanBuildDeps {
  param([Parameter(Mandatory=$true)][string]$VenvPython)
  $repo = Get-RoofSpanRepoRoot
  $backendReq = Join-Path $repo "backend\requirements.txt"
  $winReq     = Join-Path $PSScriptRoot "requirements-windows.txt"
  if (-not (Test-Path $backendReq)) { throw "Missing backend requirements: $backendReq" }
  if (-not (Test-Path $winReq))     { throw "Missing Windows build requirements: $winReq" }
  Write-Host "==> Installing RoofSpan Windows build dependencies..."
  & $VenvPython -m pip install --upgrade pip *> $null
  if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in the RoofSpan build venv." }
  & $VenvPython -m pip install -r $backendReq
  if ($LASTEXITCODE -ne 0) { throw "Failed to install backend requirements ($backendReq) into the build venv." }
  & $VenvPython -m pip install -r $winReq
  if ($LASTEXITCODE -ne 0) { throw "Failed to install Windows build requirements ($winReq) into the build venv." }
}

function Test-RoofSpanBuildDeps {
  # True only if BOTH build dependencies import cleanly through the exact venv interpreter.
  param([Parameter(Mandatory=$true)][string]$VenvPython)
  & $VenvPython -c "import PyInstaller" 2>$null
  $havePyInstaller = ($LASTEXITCODE -eq 0)
  & $VenvPython -c "import win32serviceutil" 2>$null
  $havePywin32 = ($LASTEXITCODE -eq 0)
  return ($havePyInstaller -and $havePywin32)
}

function Get-RoofSpanBuildPython {
  $repo = Get-RoofSpanRepoRoot
  $venvDir = Join-Path $repo ".venv"
  $venvPython = Join-Path $venvDir "Scripts\python.exe"

  if (-not (Test-Path $venvPython)) {
    New-RoofSpanVenv -VenvDir $venvDir
    if (-not (Test-Path $venvPython)) { throw "venv creation did not produce '$venvPython'." }
    Install-RoofSpanBuildDeps -VenvPython $venvPython
  }
  elseif (-not (Test-RoofSpanBuildDeps -VenvPython $venvPython)) {
    # Existing but incomplete venv -> repair deterministically instead of throwing "pyinstaller not found".
    Write-Host "==> Repairing RoofSpan Windows build virtual environment (missing dependencies)..."
    Install-RoofSpanBuildDeps -VenvPython $venvPython
  }

  if (-not (Test-RoofSpanBuildDeps -VenvPython $venvPython)) {
    throw "RoofSpan build venv still lacks PyInstaller and/or pywin32 after install. Inspect '$venvDir' and the requirements files."
  }

  $pyVer  = (& $venvPython -c "import platform; print(platform.python_version())").Trim()
  $pyiVer = (& $venvPython -c "import PyInstaller,sys; sys.stdout.write(PyInstaller.__version__)").Trim()
  Write-Host "==> Python build environment: $venvPython"
  Write-Host "==> Python version: $pyVer"
  Write-Host "==> PyInstaller version: $pyiVer"

  return $venvPython
}
