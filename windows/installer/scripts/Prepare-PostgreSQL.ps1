<#
  RoofSpan PostgreSQL preparation + safety validation. Carried as a Burn PAYLOAD (Name
  "Prepare-PostgreSQL.ps1") inside RoofSpanSetup.exe and executed by the OS PowerShell BEFORE the EDB
  PostgreSQL installer. Living in a real script file (not inline Burn InstallArguments) is REQUIRED:
  WiX Burn formats '[...]' tokens in InstallArguments, which silently strips PowerShell type accelerators
  such as [string], [Convert], [Security.Cryptography...], [Text.Encoding], [IO.File] and corrupts the
  command. Payload file contents are NOT formatted by Burn.

  This script decides whether a fresh PostgreSQL install is safe and prepares its credentials. It ALWAYS
  runs (no InstallCondition) so it can reason about every state, and it HALTS (non-zero, Vital) before the
  EDB installer when it is not safe to proceed. It handles these states explicitly:

    - Absent (clean machine)              -> generate/honor the superuser password + write the option
                                             file so the EDB installer runs.
    - Existing service + saved credential -> no-op exit 0 (the separate Vital Verify-PostgreSQL.ps1 step
                                             then proves the server is actually healthy - version,
                                             credentials, connectivity - before Office is installed).
    - Legacy service + roofspan.env       -> preserve the service and application credential; the Vital
                                             verify step must authenticate before Office installs.
    - Unrelated PostgreSQL on port 5432   -> STOP (exit 1) with an actionable message. RoofSpan never
                                             stops, reconfigures, or modifies another application's
                                             service or database.
    - Incomplete/stale RoofSpan install   -> repair ONLY when ownership can be established AND data is
                                             preserved; otherwise STOP (exit 1) with an actionable message.

  Credential contract (unchanged): honor an admin-supplied -PgSuperPassword, else generate a
  cryptographically strong random one; DPAPI-protect it (LocalMachine) to identity\pg_super.bin for
  RoofSpan first-run; write the transient EDB option file identity\pg_install.optionfile with
  superpassword=<password>. An EXISTING pg_super.bin is NEVER overwritten (so an existing database that
  still uses the previous password is preserved). The password is NEVER written to stdout/stderr, and the
  transient plaintext option file is removed on any handled failure path.
#>
[CmdletBinding()]
param([string]$PgSuperPassword = '')

$ErrorActionPreference = 'Stop'

$identityDir = 'C:\ProgramData\RoofSpan\identity'
$pgSuperBin  = Join-Path $identityDir 'pg_super.bin'
$optionFile  = Join-Path $identityDir 'pg_install.optionfile'
$serviceName = 'RoofSpanPostgreSQL'
$pgPort      = 5432
$diagLog     = 'C:\ProgramData\RoofSpan\prereq-diag.log'
$configFile  = 'C:\ProgramData\RoofSpan\config\roofspan.env'

function Write-Diag([string]$m) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $diagLog) | Out-Null
        Add-Content -Path $diagLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' ' + $m)
    } catch {}
}

# Durable breadcrumb so a post-mortem can establish that PowerShell + this script actually STARTED
# (Burn does not capture an ExePackage's stdout, so this file is the reliable "did it run" signal).
Write-Diag 'PREP-START'

function Remove-OptionFileQuietly {
    if (Test-Path $optionFile) { Remove-Item -Force $optionFile -ErrorAction SilentlyContinue }
}

function Stop-WithError([string]$message) {
    # Never leave a transient plaintext credential behind on a handled failure path.
    Remove-OptionFileQuietly
    Write-Diag ("PREP-STOP: " + $message)
    Write-Host "ROOFSPAN-PREREQ-ERROR: $message"
    exit 1
}

# --- 1) A registered RoofSpanPostgreSQL service means a prior (managed) install. Validate ownership. ---
$svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
$secretPresent = Test-Path $pgSuperBin
if ($svc) {
    if ($secretPresent) {
        # Existing credential; the mandatory health gate still authenticates before Office installs.
        Write-Host "RoofSpan-managed PostgreSQL service is present and owned by RoofSpan; skipping preparation."
        Write-Diag 'PREP-END-SKIP-MANAGED'
        exit 0
    }
    if (Test-Path $configFile -PathType Leaf) {
        # Older provisioned installs can have only the application credential. Do not generate a
        # replacement superuser password or run EDB over their database. Verify-PostgreSQL.ps1 must
        # authenticate this exact local application connection before the Office MSI is allowed to run.
        Write-Host "Existing RoofSpan configuration found; preserving PostgreSQL for legacy credential validation."
        Write-Diag 'PREP-END-SKIP-LEGACY'
        exit 0
    }
    Stop-WithError ("A '$serviceName' service already exists but neither its saved superuser credential " +
        "($pgSuperBin) nor its application configuration ($configFile) is available. Restore the matching " +
        "configuration/identity backup or contact RoofSpan support. Do not delete the database, remove " +
        "the service, or reset its password. Setup stopped before reinstalling PostgreSQL.")
}

if (Test-Path $configFile) {
    Stop-WithError ("An existing RoofSpan configuration ($configFile) was found but the '$serviceName' " +
        "service is missing. Restore the existing database service or contact RoofSpan support. " +
        "Do not delete the configuration or database files; setup will not create a replacement database.")
}

# --- 2) No RoofSpan service. Port 5432 must be free (RoofSpan requires it and will not touch others). ---
$listening = $null
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $listening = Get-NetTCPConnection -LocalPort $pgPort -State Listen -ErrorAction SilentlyContinue
} else {
    $listening = (netstat -ano | Select-String -Pattern (':' + $pgPort + '\s') | Select-String -Pattern 'LISTENING')
}
if ($listening) {
    Stop-WithError ("TCP port $pgPort is already in use by another application (most likely an existing " +
        "PostgreSQL server). RoofSpan requires port $pgPort and will not stop, reconfigure, or modify " +
        "another application's service or database. Resolution: stop or reconfigure the other service so " +
        "port $pgPort is free, then re-run RoofSpanSetup.exe.")
}

# --- 3) No service + a leftover RoofSpan credential = an incomplete/stale prior install we cannot safely
#         reconcile without risking existing data. Do NOT overwrite the stored superuser password. ---
if ($secretPresent) {
    Stop-WithError ("A RoofSpan PostgreSQL credential ($pgSuperBin) exists but the '$serviceName' service " +
        "is not registered - an incomplete or interrupted prior installation. RoofSpan will not overwrite " +
        "the stored superuser password (an existing database may still use it). Resolution: if you have a " +
        "backup of the prior RoofSpan database, restore the service; otherwise back up and remove " +
        "'$identityDir' and re-run RoofSpanSetup.exe, or contact RoofSpan support.")
}

# --- 4) Clean machine: honor a supplied password or generate a strong random one; DPAPI-protect it and
#         write the transient option file for the EDB installer. Wrapped so a failure removes the plaintext. ---
try {
    $pw = $PgSuperPassword
    if ([string]::IsNullOrWhiteSpace($pw)) {
        $bytes = New-Object byte[] 24
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $pw = 'Rs1!' + ([System.Convert]::ToBase64String($bytes) -replace '[+/=]', 'X')
    }

    New-Item -ItemType Directory -Force -Path $identityDir | Out-Null

    Add-Type -AssemblyName System.Security
    $protected = [System.Security.Cryptography.ProtectedData]::Protect(
        [System.Text.Encoding]::UTF8.GetBytes($pw),
        $null,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine)
    [System.IO.File]::WriteAllBytes($pgSuperBin, $protected)

    Set-Content -Encoding ASCII -Path $optionFile -Value ('superpassword=' + $pw)
} catch {
    # Do not persist raw exception text that might contain credential material.
    Stop-WithError "PostgreSQL credential preparation failed. Check access to the RoofSpan identity folder and Windows DPAPI; existing database files were not changed."
}

Write-Diag 'PREP-END-OK'
exit 0
