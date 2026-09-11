<#
  RoofSpan PostgreSQL health gate. Carried as a Burn PAYLOAD (Name "Verify-PostgreSQL.ps1") inside
  RoofSpanSetup.exe and run (Vital) AFTER the EDB installer + cleanup and BEFORE the Office MSI. It proves
  the RoofSpan-managed PostgreSQL is genuinely usable - not merely that a service exists:

    - the RoofSpanPostgreSQL Windows service is registered (else the EDB install failed / is absent),
    - the RoofSpan DPAPI superuser credential authenticates over TCP on 127.0.0.1:5432, and
    - the server version is compatible (>= the supported floor).

  This validates BOTH the fresh-install path (EDB just ran) AND the skip path (a pre-existing managed
  install must actually be healthy, not just present). On any failure it STOPS the chain with an
  actionable message so Office is never installed against a missing or broken database. The superuser
  password is decrypted only in memory and is NEVER written to stdout/stderr or a log.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$identityDir = 'C:\ProgramData\RoofSpan\identity'
$pgSuperBin  = Join-Path $identityDir 'pg_super.bin'
$optionFile  = Join-Path $identityDir 'pg_install.optionfile'
$serviceName = 'RoofSpanPostgreSQL'
$pgHost      = '127.0.0.1'
$pgPort      = 5432
$minVersion  = 130000   # server_version_num floor (PostgreSQL 13); RoofSpan ships and supports newer.
$diagLog     = 'C:\ProgramData\RoofSpan\prereq-diag.log'

function Write-Diag([string]$m) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $diagLog) | Out-Null
        Add-Content -Path $diagLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' ' + $m)
    } catch {}
}

function Stop-WithError([string]$message) {
    Write-Diag 'VERIFY-STOP'
    Write-Host "ROOFSPAN-PREREQ-ERROR: $message"
    exit 1
}

Write-Diag 'VERIFY-START'

# 0) The transient plaintext option file MUST be gone before Office proceeds. This enforces cleanup even
#    if the (non-vital) cleanup step failed or was skipped, so the plaintext superuser password is never
#    left on disk when Office installs.
if (Test-Path $optionFile) {
    Stop-WithError ("the transient PostgreSQL option file ($optionFile) still exists - it holds the " +
        "plaintext superuser password and cleanup did not remove it. Delete it and re-run RoofSpanSetup.exe.")
}

# 1) The RoofSpan-managed service must exist. If not, the EDB installer did not produce it.
$svc = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction SilentlyContinue
if (-not $svc) {
    Stop-WithError ("PostgreSQL installation did not complete: the '$serviceName' service is not present. " +
        "The bundled PostgreSQL installer likely failed. Review the RoofSpan setup log, ensure port $pgPort " +
        "is free, and re-run RoofSpanSetup.exe.")
}

# 2) The RoofSpan credential must exist and decrypt (LocalMachine DPAPI, as SYSTEM).
if (-not (Test-Path $pgSuperBin)) {
    Stop-WithError ("The RoofSpan PostgreSQL credential ($pgSuperBin) is missing, so the installed database " +
        "cannot be validated. Re-run RoofSpanSetup.exe or contact RoofSpan support.")
}

# 3) Locate psql.exe from the service's own image path (the exact EDB install servicing this machine).
$imagePath = $svc.PathName
if ($imagePath -match '^\s*"([^"]+)"') { $svcExe = $matches[1] } else { $svcExe = ($imagePath -split '\s+')[0] }
$binDir = Split-Path $svcExe -Parent
$psql = Join-Path $binDir 'psql.exe'
if (-not (Test-Path $psql)) {
    Stop-WithError ("Could not find psql.exe for the '$serviceName' service (looked in '$binDir'). The " +
        "PostgreSQL installation appears incomplete. Re-run RoofSpanSetup.exe or contact RoofSpan support.")
}

# 4) Authenticate over TCP with the decrypted superuser credential and read the server version. The
#    password lives only in memory and PGPASSWORD, cleared immediately afterward; it is never logged.
Add-Type -AssemblyName System.Security
$enc = [System.IO.File]::ReadAllBytes($pgSuperBin)
$pw = [System.Text.Encoding]::UTF8.GetString(
    [System.Security.Cryptography.ProtectedData]::Unprotect(
        $enc, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine))

$verOut = $null
$code = 1
try {
    $env:PGPASSWORD = $pw
    $verOut = & $psql -h $pgHost -p $pgPort -U postgres -d postgres -w -tAc 'SHOW server_version_num;' 2>&1
    $code = $LASTEXITCODE
} finally {
    $env:PGPASSWORD = ''
    $pw = $null
}

if ($code -ne 0) {
    Stop-WithError ("Could not connect to or authenticate against the RoofSpan-managed PostgreSQL on " +
        "$pgHost`:$pgPort with the stored superuser credential. The server may not be running or its " +
        "password may have diverged. Start the '$serviceName' service and re-run RoofSpanSetup.exe, or " +
        "contact RoofSpan support (existing data is left untouched).")
}

$verNum = 0
$firstLine = ($verOut | Select-Object -First 1)
[void][int]::TryParse((("$firstLine").Trim()), [ref]$verNum)
if ($verNum -lt $minVersion) {
    Stop-WithError ("The detected PostgreSQL server_version_num ($verNum) is older than the supported " +
        "minimum ($minVersion). Upgrade PostgreSQL to a supported version and re-run RoofSpanSetup.exe.")
}

Write-Host "RoofSpan PostgreSQL health check passed (server_version_num=$verNum)."
Write-Diag 'VERIFY-END-OK'
exit 0
