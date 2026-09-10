<#
  RoofSpan PostgreSQL cleanup. Carried as a Burn PAYLOAD inside RoofSpanSetup.exe and executed by the OS
  PowerShell AFTER the EDB PostgreSQL installer. Removes ONLY the transient EDB option file; the
  DPAPI-protected identity\pg_super.bin is intentionally preserved because RoofSpan first-run needs it.
  Kept in a script file (not inline) so it can never regress into a Burn-formatted-string failure.
#>
$ErrorActionPreference = 'SilentlyContinue'

$optionFile = 'C:\ProgramData\RoofSpan\identity\pg_install.optionfile'
if (Test-Path $optionFile) { Remove-Item -Force $optionFile }

exit 0
