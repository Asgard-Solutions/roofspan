#Requires -Version 5.1
<#
.SYNOPSIS
  Re-open RoofSpan Office's local first-run company/owner setup wizard.
.DESCRIPTION
  Read-only dry run by default. -Apply stops the RoofSpan application services,
  makes and verifies a FULL pg_dump backup, then removes ONLY the initial Owner
  user, refresh tokens, company_profile and setup_recovery keys.

  Refuses to run if multiple users or any other business data are present.
  Preserves installation identity, license cache, Control Plane binding,
  audit log, migrations, and all other configuration.

  Run in an elevated PowerShell window on the RoofSpan Office Windows PC.
.EXAMPLE
  .\Reset-RoofSpanCompanySetup.ps1
  .\Reset-RoofSpanCompanySetup.ps1 -Apply
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$ConfigPath = 'C:\ProgramData\RoofSpan\config\roofspan.env'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-EnvSetting {
    param([string]$File, [string]$Name)
    foreach ($line in (Get-Content -LiteralPath $File -Encoding UTF8)) {
        if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim().Trim([char[]]@([char]34, [char]39))
        }
    }
    return $null
}

function Resolve-PgExecutable {
    param([string]$Name, [string]$BinDirectory)
    foreach ($dir in @($BinDirectory, 'C:\Program Files\PostgreSQL\16\bin',
                      'C:\Program Files\PostgreSQL\17\bin', 'C:\Program Files\PostgreSQL\15\bin')) {
        if (-not [string]::IsNullOrWhiteSpace($dir)) {
            $candidate = Join-Path $dir ($Name + '.exe')
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    $command = Get-Command ($Name + '.exe') -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Cannot find $Name.exe; check ROOFSPAN_PG_BIN in roofspan.env."
}

function Invoke-Psql {
    param([string]$Sql)
    $output = & $script:PsqlPath -X -w -v ON_ERROR_STOP=1 -q -t -A -h $script:PgHost -p $script:PgPort -U $script:PgUser -d $script:PgDatabase -c $Sql
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL command failed; no reset was confirmed.' }
    return $output
}

# Whitelist only first-run-owned records and harmless infrastructure/metadata.
# Re-check in the reset transaction, not just before stopping the services.
$guardSql = @'
DO $guard$
DECLARE t record; has_rows boolean; user_count bigint;
BEGIN
  SELECT count(*) INTO user_count FROM public.users;
  IF user_count > 1 THEN
    RAISE EXCEPTION 'Reset blocked: more than one user exists';
  END IF;
  IF EXISTS (SELECT 1 FROM public.users WHERE role <> 'owner') THEN
    RAISE EXCEPTION 'Reset blocked: existing user is not an owner';
  END IF;
  FOR t IN SELECT schemaname, tablename FROM pg_catalog.pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN (
                'users', 'refresh_tokens', 'app_config', 'audit_logs',
                'license_cache', 'alembic_version', 'spatial_ref_sys')
  LOOP
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I)', t.schemaname, t.tablename) INTO has_rows;
    IF has_rows THEN
      RAISE EXCEPTION 'Reset blocked: business data exists in %.%', t.schemaname, t.tablename;
    END IF;
  END LOOP;
END
$guard$;
'@

$resetSql = @'
BEGIN;
LOCK TABLE public.users, public.refresh_tokens, public.app_config IN ACCESS EXCLUSIVE MODE;
DO $guard$
DECLARE t record; has_rows boolean; user_count bigint;
BEGIN
  SELECT count(*) INTO user_count FROM public.users;
  IF user_count > 1 THEN
    RAISE EXCEPTION 'Reset blocked: more than one user exists';
  END IF;
  IF EXISTS (SELECT 1 FROM public.users WHERE role <> 'owner') THEN
    RAISE EXCEPTION 'Reset blocked: existing user is not an owner';
  END IF;
  FOR t IN SELECT schemaname, tablename FROM pg_catalog.pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN (
                'users', 'refresh_tokens', 'app_config', 'audit_logs',
                'license_cache', 'alembic_version', 'spatial_ref_sys')
  LOOP
    EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.%I)', t.schemaname, t.tablename) INTO has_rows;
    IF has_rows THEN
      RAISE EXCEPTION 'Reset blocked: business data exists in %.%', t.schemaname, t.tablename;
    END IF;
  END LOOP;
END
$guard$;
DELETE FROM public.refresh_tokens;
DELETE FROM public.users;
DELETE FROM public.app_config WHERE key IN ('company_profile', 'setup_recovery');
COMMIT;
'@

$runningBefore = @()
try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "RoofSpan configuration not found: $ConfigPath"
    }
    $dbUrl = Read-EnvSetting -File $ConfigPath -Name 'DATABASE_URL'
    if (-not $dbUrl) { throw 'DATABASE_URL is missing from RoofSpan configuration.' }
    $uri = [Uri]($dbUrl -replace '^postgresql\+(asyncpg|psycopg)://', 'postgresql://')
    $script:PgHost = $uri.Host
    $script:PgPort = if ($uri.Port -gt 0) { [string]$uri.Port } else { '5432' }
    $parts = $uri.UserInfo.Split(':', 2)
    if ($parts.Count -ne 2) { throw 'DATABASE_URL is missing the user/password.' }
    $script:PgUser = [Uri]::UnescapeDataString($parts[0])
    $script:PgDatabase = [Uri]::UnescapeDataString($uri.AbsolutePath.Trim('/'))
    $env:PGPASSWORD = [Uri]::UnescapeDataString($parts[1])

    if ($uri.Scheme -ne 'postgresql' -or
        $script:PgHost -notin @('127.0.0.1', 'localhost', '::1') -or
        $script:PgDatabase -ne 'roofspan' -or $script:PgUser -ne 'roofspan') {
        throw 'Safety check failed: only the local roofspan business DB may be reset.'
    }
    $pgBin = Read-EnvSetting -File $ConfigPath -Name 'ROOFSPAN_PG_BIN'
    $script:PsqlPath = Resolve-PgExecutable -Name 'psql' -BinDirectory $pgBin
    $pgDumpPath = Resolve-PgExecutable -Name 'pg_dump' -BinDirectory $pgBin
    $pgRestorePath = Resolve-PgExecutable -Name 'pg_restore' -BinDirectory $pgBin

    [void](Invoke-Psql -Sql $guardSql)
    $count = (Invoke-Psql -Sql 'SELECT COUNT(*) FROM public.users;') | Select-Object -First 1
    Write-Host "Safety checks passed. Users: $count."
    Write-Host 'Target: initial Owner account, refresh tokens, company_profile, setup_recovery.'
    Write-Host 'Preserved: business records, audit logs, installation keys, license and cloud registration.'
    if (-not $Apply) {
        Write-Host 'DRY RUN ONLY. Re-run with -Apply to back up and reset.'
        return
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run PowerShell as Administrator when using -Apply.'
    }
    $confirmation = Read-Host 'Type RESET ROOFSPAN SETUP to delete the current Owner login'
    if ($confirmation -cne 'RESET ROOFSPAN SETUP') { throw 'Cancelled: confirmation did not match.' }

    foreach ($name in @('RoofSpanUpdateService', 'RoofSpanRelayConnector', 'RoofSpanBackend')) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -ne 'Stopped') {
            if ($svc.Status -ne 'Running') {
                throw "Cannot safely stop $name (status $($svc.Status))."
            }
            $runningBefore += $name
            Stop-Service -Name $name -ErrorAction Stop
            (Get-Service -Name $name).WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(45))
        }
    }

    [void](Invoke-Psql -Sql $guardSql)
    $backupDir = Read-EnvSetting -File $ConfigPath -Name 'ROOFSPAN_BACKUP_DIR'
    if (-not $backupDir) { $backupDir = 'C:\ProgramData\RoofSpan\backups' }
    if (-not (Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $backupPath = Join-Path $backupDir ('roofspan_' + $stamp + '_before_setup_reset.dump')
    Write-Host "Backing up database: $backupPath"
    & $pgDumpPath -w -h $script:PgHost -p $script:PgPort -U $script:PgUser -d $script:PgDatabase -Fc -f $backupPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $backupPath) -or
        (Get-Item -LiteralPath $backupPath).Length -lt 5) {
        throw 'Backup failed; setup records were not changed.'
    }
    & $pgRestorePath --list $backupPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Backup validation failed; setup records were not changed.' }
    Write-Host 'Full database backup verified.'

    [void](Invoke-Psql -Sql $resetSql)
    $verified = (Invoke-Psql -Sql "SELECT CASE WHEN (SELECT COUNT(*) FROM public.users) = 0 AND NOT EXISTS (SELECT 1 FROM public.app_config WHERE key = 'company_profile') THEN 'true' ELSE 'false' END;") | Select-Object -First 1
    if ($verified -ne 'true') { throw 'Reset did not verify; inspect the database and saved backup.' }
    Write-Host 'Local setup reset. Open RoofSpan Office and create the company and Owner again.'
    Write-Host "Backup saved: $backupPath"
}
finally {
    foreach ($name in @('RoofSpanBackend', 'RoofSpanRelayConnector', 'RoofSpanUpdateService')) {
        if ($runningBefore -contains $name) {
            try { Start-Service -Name $name -ErrorAction Stop }
            catch { Write-Warning "Could not restart $name; start it manually: $($_.Exception.Message)" }
        }
    }
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
