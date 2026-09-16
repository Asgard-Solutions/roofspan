<# CI-only destructive fixture setup on the disposable runner, followed by a data-preserving upgrade.
   The real clean install has already provisioned PostgreSQL and Office. Remove ONLY that fixture's
   superuser secret to reproduce an older installation, retaining its database and application config.
   Never run this script on a customer machine.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$SetupExe)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'This fixture may run only on the disposable GitHub Actions Windows runner.'
}

$cfg = 'C:\ProgramData\RoofSpan\config\roofspan.env'
$secret = 'C:\ProgramData\RoofSpan\identity\pg_super.bin'
$initialText = Get-Content $cfg -Raw
$line = @($initialText -split "`n" | Where-Object { $_ -match '^DATABASE_URL=' })
if ($line.Count -ne 1) { throw 'Fixture is missing its provisioned application connection.' }
$uri = [Uri](($line[0].Trim() -replace '^DATABASE_URL=postgresql\+asyncpg:', 'postgresql:'))
$appPw = [Uri]::UnescapeDataString(($uri.UserInfo -split ':', 2)[1])
$fixturePort = 5432
$legacyPort = 5442
$svcBefore = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
if ($svcBefore.PathName -notmatch '^"([^"]+)"') { throw 'Unexpected EDB service executable path.' }
$psql = Join-Path (Split-Path $Matches[1]) 'psql.exe'
$diag = 'C:\ProgramData\RoofSpan\prereq-diag.log'

function Invoke-Probe([string]$Sql) {
    $result = & $psql -X -h 127.0.0.1 -p $fixturePort -U roofspan -d roofspan -w -v ON_ERROR_STOP=1 -tAc $Sql 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Legacy fixture SQL check failed (details withheld to protect credentials).' }
    return (($result | ForEach-Object { "$_" }) -join "`n").Trim()
}

function Invoke-Upgrade([string]$Log, [bool]$ShouldSucceed) {
    $p = Start-Process $SetupExe -ArgumentList @('/quiet','/norestart','/log',"`"$Log`"") -Wait -PassThru
    $burn = Get-Content $Log -Raw
    if ($burn -match 'Applying execute package: PostgreSQLPrereq,') { throw 'Upgrade tried to reinstall EDB over an existing database.' }
    if ($ShouldSucceed) {
        if ($p.ExitCode -notin @(0, 3010)) { throw "Legacy upgrade failed (exit $($p.ExitCode)); inspect Burn and prerequisite logs." }
        if ($burn -notmatch 'Applied execute package: RoofSpanOfficeMsi, result: 0x0') { throw 'Office MSI did not execute successfully.' }
    } else {
        if ($p.ExitCode -in @(0, 3010)) { throw 'Invalid application credential was accepted.' }
        if ($burn -match 'Applying execute package: RoofSpanOfficeMsi,') { throw 'Office MSI ran before legacy authentication succeeded.' }
    }
}

try {
    $env:PGPASSWORD = $appPw
    $env:PGCONNECT_TIMEOUT = '10'
    $probe = [guid]::NewGuid().ToString()
    Invoke-Probe 'CREATE TABLE public.roofspan_installer_upgrade_probe (value text PRIMARY KEY);' | Out-Null
    Invoke-Probe "INSERT INTO public.roofspan_installer_upgrade_probe VALUES ('$probe');" | Out-Null

    # Reconfigure this disposable fixture to the real customer regression: existing RoofSpan PostgreSQL
    # on local port 5442 with only its application credential. The production installer must read the
    # saved port and must not rewrite/restart PostgreSQL during the subsequent upgrade.
    Add-Type -AssemblyName System.Security
    $enc = [IO.File]::ReadAllBytes($secret)
    $superPw = [Text.Encoding]::UTF8.GetString(
        [Security.Cryptography.ProtectedData]::Unprotect(
            $enc, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine))
    try {
        $env:PGPASSWORD = $superPw
        & $psql -X -h 127.0.0.1 -p 5432 -U postgres -d postgres -w -v ON_ERROR_STOP=1 `
            -tAc "ALTER SYSTEM SET port = '$legacyPort';" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not configure the CI PostgreSQL fixture port.' }
    } finally {
        $superPw = $null
        $env:PGPASSWORD = $appPw
    }

    Stop-Service RoofSpanRelayConnector -Force -ErrorAction SilentlyContinue
    Stop-Service RoofSpanBackend -Force -ErrorAction SilentlyContinue
    Restart-Service RoofSpanPostgreSQL -Force
    $fixturePort = $legacyPort
    $legacyText = [regex]::Replace(
        $initialText,
        '(?m)^(DATABASE_URL=postgresql\+asyncpg://roofspan:[^@\r\n]+@127\.0\.0\.1:)5432(/roofspan\s*)$',
        '${1}' + $legacyPort + '${2}')
    if ($legacyText -ceq $initialText) { throw 'Could not change the CI application connection to port 5442.' }
    [IO.File]::WriteAllText($cfg, $legacyText)
    $text = Get-Content $cfg -Raw
    $original = [IO.File]::ReadAllBytes($cfg)
    $cfgHash = (Get-FileHash $cfg).Hash

    $deadline = (Get-Date).AddSeconds(60)
    $ready = $false
    while (-not $ready -and (Get-Date) -lt $deadline) {
        try { $ready = (Invoke-Probe 'SELECT 1;') -eq '1' } catch { Start-Sleep 2 }
    }
    if (-not $ready) { throw 'PostgreSQL fixture did not become ready on port 5442.' }
    $started = Invoke-Probe 'SELECT pg_postmaster_start_time();'
    # This deletes only the disposable runner's generated fixture credential, never customer data.
    Remove-Item $secret -Force

    # Bad credentials must fail before Office/EDB executes. Restore the original config byte-for-byte.
    $wrong = [regex]::Replace($text, '(?m)^DATABASE_URL=.*$', "DATABASE_URL=postgresql+asyncpg://roofspan:CI_WRONG_PASSWORD@127.0.0.1:$legacyPort/roofspan")
    try {
        [IO.File]::WriteAllText($cfg, $wrong)
        Invoke-Upgrade (Join-Path $env:RUNNER_TEMP 'legacy-bad-credential.burn.log') $false
    } finally {
        [IO.File]::WriteAllBytes($cfg, $original)
    }
    if ((Invoke-Probe 'SELECT value FROM public.roofspan_installer_upgrade_probe;') -cne $probe) { throw 'Failed upgrade changed existing data.' }
    Write-Host 'OK: incorrect legacy credential blocks both Office and EDB; existing data survives.'

    Invoke-Upgrade (Join-Path $env:RUNNER_TEMP 'legacy-upgrade.burn.log') $true
    if ((Get-FileHash $cfg).Hash -ne $cfgHash) { throw 'Upgrade changed the existing application configuration.' }
    if (Test-Path $secret) { throw 'Upgrade synthesized a replacement superuser credential.' }
    if (Test-Path 'C:\ProgramData\RoofSpan\identity\pg_install.optionfile') { throw 'Upgrade created a plaintext credential file.' }
    if ((Invoke-Probe 'SELECT value FROM public.roofspan_installer_upgrade_probe;') -cne $probe) { throw 'Upgrade changed existing data.' }
    if ((Invoke-Probe 'SELECT pg_postmaster_start_time();') -cne $started) { throw 'Upgrade restarted/replaced PostgreSQL.' }
    $svcAfter = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
    if ($svcAfter.PathName -cne $svcBefore.PathName -or $svcAfter.State -ne 'Running') { throw 'Upgrade changed/stopped the PostgreSQL service.' }
    if ((Get-Content $diag -Raw) -notmatch 'VERIFY-LEGACY-APPLICATION-CREDENTIAL') { throw 'Legacy validation path did not execute.' }
    $ok = $false
    $deadline = (Get-Date).AddSeconds(180)
    while (-not $ok -and (Get-Date) -lt $deadline) {
        try { $ok = (Invoke-WebRequest 'http://127.0.0.1:8001/api/health' -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { Start-Sleep 3 }
    }
    if (-not $ok) { throw 'Office backend did not become healthy after legacy upgrade.' }
    Write-Host 'OK: real Burn/MSI legacy upgrade on port 5442 preserved data, config and PostgreSQL; Office backend is healthy.'
} finally {
    $env:PGPASSWORD = ''
    $env:PGCONNECT_TIMEOUT = ''
    $appPw = $null
    $text = $null
    $initialText = $null
    $original = $null
}
