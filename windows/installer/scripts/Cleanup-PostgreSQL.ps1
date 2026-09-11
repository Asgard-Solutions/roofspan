<#
  RoofSpan PostgreSQL cleanup. Carried as a Burn PAYLOAD (Name "Cleanup-PostgreSQL.ps1") inside
  RoofSpanSetup.exe and run AFTER the EDB installer. It removes ONLY the transient EDB option file (which
  holds the plaintext superuser password); the DPAPI-protected identity\pg_super.bin is intentionally
  preserved because RoofSpan first-run needs it.

  This step is non-vital and runs unconditionally so it also fires after an EDB FAILURE, ensuring the
  plaintext option file never lingers. It REPORTS a deletion failure (non-zero exit + actionable message).
  The separate Vital Verify-PostgreSQL.ps1 step then REQUIRES the option file to be gone before Office is
  installed, so a cleanup failure cannot silently leave the secret on disk.
#>
$ErrorActionPreference = 'Stop'

$identityDir = 'C:\ProgramData\RoofSpan\identity'
$optionFile  = Join-Path $identityDir 'pg_install.optionfile'
$diagLog     = 'C:\ProgramData\RoofSpan\prereq-diag.log'

function Write-Diag([string]$m) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $diagLog) | Out-Null
        Add-Content -Path $diagLog -Value ((Get-Date).ToUniversalTime().ToString('o') + ' ' + $m)
    } catch {}
}

Write-Diag 'CLEANUP-START'
Write-Host "RoofSpan PostgreSQL cleanup: removing the transient option file."

if (Test-Path $optionFile) {
    try {
        Remove-Item -Force $optionFile
    } catch {
        Write-Diag 'CLEANUP-DELETE-FAILED'
        Write-Host ("ROOFSPAN-PREREQ-ERROR: failed to delete the transient PostgreSQL option file " +
            "($optionFile): $($_.Exception.Message). It holds the plaintext superuser password and MUST " +
            "be removed. Delete it manually, then re-run RoofSpanSetup.exe.")
        exit 1
    }
}

# Confirm removal (defense-in-depth; the Vital Verify step also enforces this before Office).
if (Test-Path $optionFile) {
    Write-Diag 'CLEANUP-STILL-PRESENT'
    Write-Host ("ROOFSPAN-PREREQ-ERROR: the transient PostgreSQL option file ($optionFile) is still " +
        "present after cleanup. It holds the plaintext superuser password. Delete it manually, then " +
        "re-run RoofSpanSetup.exe.")
    exit 1
}

Write-Diag 'CLEANUP-END-OK'
exit 0
