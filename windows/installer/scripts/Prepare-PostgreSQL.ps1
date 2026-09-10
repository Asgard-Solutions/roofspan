<#
  RoofSpan PostgreSQL preparation. Carried as a Burn PAYLOAD inside RoofSpanSetup.exe and executed by
  the OS PowerShell BEFORE the EDB PostgreSQL installer. Living in a real script file (not inline Burn
  InstallArguments) is REQUIRED: WiX Burn formats '[...]' tokens in InstallArguments, which silently
  strips PowerShell type accelerators such as [string], [Convert], [Security.Cryptography...],
  [Text.Encoding], [IO.File] and corrupts the command. Payload file contents are NOT formatted by Burn.

  Behavior (unchanged from the previous inline implementation):
    - Honor an admin-supplied superuser password (-PgSuperPassword); otherwise generate a
      cryptographically strong random one.
    - Create C:\ProgramData\RoofSpan\identity.
    - DPAPI-protect the password (LocalMachine scope) to identity\pg_super.bin for RoofSpan first-run.
    - Write the transient EDB option file identity\pg_install.optionfile with superpassword=<password>.
  The password is NEVER written to stdout/stderr.
#>
[CmdletBinding()]
param([string]$PgSuperPassword = '')

$ErrorActionPreference = 'Stop'

$pw = $PgSuperPassword
if ([string]::IsNullOrWhiteSpace($pw)) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = 'Rs1!' + ([System.Convert]::ToBase64String($bytes) -replace '[+/=]', 'X')
}

$dir = 'C:\ProgramData\RoofSpan\identity'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Add-Type -AssemblyName System.Security
$protected = [System.Security.Cryptography.ProtectedData]::Protect(
    [System.Text.Encoding]::UTF8.GetBytes($pw),
    $null,
    [System.Security.Cryptography.DataProtectionScope]::LocalMachine)
[System.IO.File]::WriteAllBytes((Join-Path $dir 'pg_super.bin'), $protected)

Set-Content -Encoding ASCII -Path (Join-Path $dir 'pg_install.optionfile') -Value ('superpassword=' + $pw)

exit 0
