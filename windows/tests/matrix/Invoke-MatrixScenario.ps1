<#
  Run ONE installer failure-matrix scenario against the ONE tested RoofSpanSetup.exe.

  DESTRUCTIVE. Refuses to run unless matrix.py guard approves a disposable GitHub-hosted runner or an approved
  single-use disposable VM. Writes assertions.jsonl, sanitized manifests, logs and result.json to -EvidenceDir.
#>
param(
    [Parameter(Mandatory = $true)][string]$Scenario,
    [Parameter(Mandatory = $true)][string]$Setup,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$BuildInfo,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$MatrixPy = Join-Path $PSScriptRoot 'matrix.py'
$env:ROOFSPAN_MATRIX_SCENARIO = $Scenario

# Safety guard FIRST, before importing anything destructive.
& python $MatrixPy guard
if ($LASTEXITCODE -ne 0) { throw "GUARD-REFUSED: $Scenario will not run outside an approved disposable environment" }
Import-Module (Join-Path $PSScriptRoot 'MatrixLib.psm1') -Force
Initialize-Matrix $EvidenceDir
$B = Get-Content $BuildInfo -Raw | ConvertFrom-Json
$Same = @('office_msi_version', 'api_version', 'backend_build_info', 'revisions', 'services', 'config_sha256', 'identity_sha256', 'sentinel')
$PreChange = @('office_msi_version', 'backend_build_info', 'revisions', 'services', 'config_sha256', 'identity_sha256', 'sentinel')

# -- shared steps ------------------------------------------------------------------------------------------------
function Step-CleanMachine { Set-Layer 'environment'; Remove-RunnerPostgreSQL; Assert-CleanMachine }
function Assert-NHealthy([string]$Label) {
    Set-Layer 'service-startup'; Assert-OfficeServicesRunning $Label
    Set-Layer 'health-check'; Wait-OfficeHealthy -Version $B.version -BuildSha $B.git_sha
    Assert-Equal "$Label backend build identity" "$($B.version)/$($B.git_sha)/fault_injection=False" (Get-BuildInfo 'roofspan-backend')
    Register-ConfigSecrets
}
function Install-N([string]$Label = 'install-n', [string]$Exe = $Setup) {
    $code = Invoke-Setup $Exe $Label
    Assert-SetupSucceeded $Label $code
    Set-Layer 'prerequisite'
    $svc = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
    Assert-True "$Label RoofSpanPostgreSQL is a real EDB pg_ctl service" ($svc -and $svc.PathName -match 'pg_ctl\.exe') "$(if ($svc) { $svc.PathName })"
    Assert-True "$Label RoofSpanPostgreSQL running" (Wait-Until { (Get-Service RoofSpanPostgreSQL).Status -eq 'Running' } 120 'PostgreSQL Running') ''
    Assert-True "$Label pg_super.bin present" (Test-Path (Join-Path $IdentityDir 'pg_super.bin')) ''
    Assert-True "$Label transient option file removed" (-not (Test-Path (Join-Path $IdentityDir 'pg_install.optionfile'))) ''
    Assert-BurnDidNotApply $Label 'RoofSpanUpgradeCoordinator'
    Assert-NHealthy $Label
}
function New-SeededN { Step-CleanMachine; Install-N; Set-Layer 'environment'; New-Sentinel; return (Get-Manifest 'before') }
function Get-DiagOffset { $p = Join-Path $Data 'prereq-diag.log'; if (Test-Path $p) { (Get-Item $p).Length } else { 0 } }
function Get-DiagSince([long]$Offset) {
    $p = Join-Path $Data 'prereq-diag.log'
    if (-not (Test-Path $p)) { return '' }
    $bytes = [IO.File]::ReadAllBytes($p)
    if ($Offset -ge $bytes.Length) { return '' }
    return [Text.Encoding]::UTF8.GetString($bytes, [int]$Offset, $bytes.Length - [int]$Offset)
}
function Assert-RerunPreserves($Before, [string]$Label, [string[]]$Keys = $Same) {
    Assert-NHealthy $Label
    $after = Get-Manifest "after-$Label"
    Assert-ManifestKeys $Before $after $Keys $Label
    Assert-BurnDidNotApply $Label 'PostgreSQLPrereq'
    return $after
}
function Assert-SafeStopNoInstall([string]$Label, [int]$Code) {
    Set-Layer 'prerequisite'
    Assert-True "$Label setup stopped (non-zero exit)" ($Code -notin 0, 3010) "exit=$Code"
    Assert-BurnDidNotApply $Label 'PostgreSQLPrereq'
    Assert-BurnDidNotApply $Label 'RoofSpanOfficeMsi'
    Assert-True "$Label no Office product installed" (-not (Get-OfficeMsi)) ''
    Assert-True "$Label no RoofSpanPostgreSQL service created" (-not (Get-Service RoofSpanPostgreSQL -ErrorAction SilentlyContinue)) ''
}

# -- upgrade steps -------------------------------------------------------------------------------------------------
function Start-UpgradeContext([string]$Which, [switch]$NeedsPending, [switch]$NeedsSuper, [int]$Rows = 500) {
    Step-CleanMachine
    $bv = Install-Baseline $Which
    Set-Layer 'environment'
    Register-ConfigSecrets
    if ($NeedsSuper) { Assert-True "baseline $Which is RoofSpan-managed (superuser credential available)" ([bool](Get-SuperPassword)) '' }
    New-Sentinel $Rows
    $before = Get-Manifest 'before'
    if ($NeedsPending -and (@($B.heads.business) -contains $before.revisions.business)) {
        throw "BLOCKED_NO_PENDING_MIGRATION: baseline $Which business revision $($before.revisions.business) is already N's head; N has no migration to fail"
    }
    return @{ Which = $Which; Version = $bv; Before = $before }
}
function Complete-Upgrade($Ctx, $Process, [string]$Label = 'upgrade') {
    $Ctx.Code = Wait-Setup $Process 180
    if (Test-Path $StateFile) { Copy-Item $StateFile (Get-EvidencePath "state-$Label.json") -Force }
    $Ctx.State = Get-CoordinatorState
    $Ctx.History = Get-StateHistory $Ctx.State
    Write-Host ("coordinator: " + $(if ($Ctx.State) { "$($Ctx.State.state) history=$($Ctx.History -join '>') error=$(Protect-Text "$($Ctx.State.error)")" } else { 'no state' }))
}
function Assert-UpgradeSuccess($Ctx, [string]$Label = 'upgrade', [string]$Outcome = 'success') {
    Assert-SetupSucceeded $Label $Ctx.Code
    Set-Layer 'recovery'
    Assert-True "$Label coordinator COMPLETE" ($Ctx.State -and $Ctx.State.state -eq 'COMPLETE') "state=$(if ($Ctx.State) { $Ctx.State.state })"
    Assert-NHealthy $Label
    $after = Get-Manifest "after-$Label"
    Assert-ManifestKeys $Ctx.Before $after @('sentinel', 'identity_sha256', 'config_key_sha256') $Label
    Set-Layer 'migration'
    Assert-Equal "$Label business schema at N head" ((@($B.heads.business) | Sort-Object) -join ',') $after.revisions.business
    Assert-Equal "$Label control-plane schema at N head" ((@($B.heads.control_plane) | Sort-Object) -join ',') $after.revisions.control_plane
    Write-Assertion "outcome:$Outcome" $true "$($Ctx.Which) $($Ctx.Version) -> $($B.version); sentinel, identity and secrets preserved"
}
function Assert-PreviousRestored($Ctx, [string]$Label, [string[]]$Keys) {
    Set-Layer 'recovery'
    Assert-OfficeServicesRunning $Label
    Wait-OfficeHealthy -Version $Ctx.Version
    $after = Get-Manifest "after-$Label"
    Assert-ManifestKeys $Ctx.Before $after $Keys $Label
}
function Assert-UpgradeSafeStop($Ctx, [string]$Label = 'upgrade') {
    Set-Layer 'backup'
    Assert-True "$Label setup reported failure" ($Ctx.Code -notin 0, 3010) "exit=$($Ctx.Code)"
    Assert-True "$Label coordinator ROLLED_BACK" ($Ctx.State -and $Ctx.State.state -eq 'ROLLED_BACK') "state=$(if ($Ctx.State) { $Ctx.State.state })"
    Assert-True "$Label stopped before INSTALLING (no unsafe mutation)" ($Ctx.History -notcontains 'INSTALLING') ($Ctx.History -join '>')
    $bdir = "$($Ctx.State.backup_dir)"
    Assert-True "$Label new MSI never ran" (-not ($bdir -and (Test-Path (Join-Path $bdir 'install-new.log')))) "backup_dir=$bdir"
    Assert-PreviousRestored $Ctx $Label $PreChange
    Write-Assertion 'outcome:safe_stop' $true "stopped in $(@($Ctx.History | Where-Object { $_ -ne 'ROLLED_BACK' })[-1]) before any change"
}
function Assert-UpgradeRollback($Ctx, [string]$Label = 'upgrade') {
    Set-Layer 'recovery'
    Assert-True "$Label setup reported failure" ($Ctx.Code -notin 0, 3010) "exit=$($Ctx.Code)"
    Assert-True "$Label coordinator ROLLED_BACK" ($Ctx.State -and $Ctx.State.state -eq 'ROLLED_BACK') "state=$(if ($Ctx.State) { $Ctx.State.state }) recovery_error=$(if ($Ctx.State) { $Ctx.State.recovery_error })"
    Assert-True "$Label failure happened after mutation began (INSTALLING reached)" ($Ctx.History -contains 'INSTALLING') ($Ctx.History -join '>')
    Assert-True "$Label RESTORING ran" ($Ctx.History -contains 'RESTORING') ($Ctx.History -join '>')
    Assert-PreviousRestored $Ctx $Label ($PreChange + 'api_version')
    if (Get-SuperPassword) {
        $failed = Invoke-Sql "SELECT datname FROM pg_database WHERE datname = 'roofspan_failed_$($Ctx.State.attempt_id)'" 'postgres' -Super
        Assert-True "$Label failed database retained for support" ($failed -eq "roofspan_failed_$($Ctx.State.attempt_id)") ''
    }
    Assert-True "$Label live database has no injected fault objects" ((Invoke-Sql "SELECT count(*) FROM pg_namespace WHERE nspname='rs_matrix_fault'") -eq '0') ''
    Write-Assertion 'outcome:rollback' $true "recovered from $(@($Ctx.History | Where-Object { $_ -notin 'RESTORING', 'ROLLED_BACK' })[-1]) to $($Ctx.Version)"
}
function Get-MigrateFault($Ctx) {
    $log = Join-Path "$($Ctx.State.backup_dir)" 'migrate.log'
    $text = if (Test-Path $log) { Get-Content $log -Raw } else { '' }
    $m = [regex]::Match($text, 'RS_MATRIX_INJECTED_MIGRATION_FAILURE ddl_before_failure=(\d+) point=(\S+)')
    Assert-True 'migrate.log records the injected migration failure' $m.Success ''
    return @{ Ddl = [int]$m.Groups[1].Value; Point = $m.Groups[2].Value }
}
function Enable-MigrationFault([string]$Mode) {
    Set-Layer 'environment'
    $role = (Get-AppDb).User
    $first = if ($Mode -eq 'first') { 'true' } else { 'false' }
    $heads = 'ARRAY[' + ((@($B.heads.business) | ForEach-Object { "'$_'" }) -join ',') + ']::text[]'
    $sql = @"
CREATE SCHEMA rs_matrix_fault;
GRANT USAGE ON SCHEMA rs_matrix_fault TO PUBLIC;
CREATE FUNCTION rs_matrix_fault.on_ddl() RETURNS event_trigger LANGUAGE plpgsql AS `$f`$
BEGIN
  IF session_user = '$role' THEN
    IF $first THEN RAISE EXCEPTION 'RS_MATRIX_INJECTED_MIGRATION_FAILURE ddl_before_failure=0 point=first-ddl'; END IF;
    PERFORM set_config('rs_matrix.ddl', (coalesce(nullif(current_setting('rs_matrix.ddl', true), ''), '0')::int + 1)::text, false);
  END IF;
END `$f`$;
CREATE EVENT TRIGGER rs_matrix_ddl ON ddl_command_start EXECUTE FUNCTION rs_matrix_fault.on_ddl();
CREATE FUNCTION rs_matrix_fault.on_version() RETURNS trigger LANGUAGE plpgsql AS `$f`$
BEGIN
  IF session_user = '$role' AND ($first OR NEW.version_num = ANY($heads)) THEN
    RAISE EXCEPTION 'RS_MATRIX_INJECTED_MIGRATION_FAILURE ddl_before_failure=% point=%',
      coalesce(nullif(current_setting('rs_matrix.ddl', true), ''), '0'), NEW.version_num;
  END IF;
  RETURN NEW;
END `$f`$;
CREATE TRIGGER rs_matrix_version BEFORE INSERT OR UPDATE ON public.alembic_version FOR EACH ROW EXECUTE FUNCTION rs_matrix_fault.on_version();
"@
    Invoke-Sql $sql 'roofspan' -Super -AsFile | Out-Null
    Write-Assertion "fault armed: migration ($Mode)" $true 'armed after BACKUP_VERIFIED, so the verified backup is fault-free'
}
function Watch-RelayDuringHealth($Process) {
    Wait-CoordinatorState @('HEALTH_CHECKING') 7200 $Process | Out-Null
    $stops = 0
    while (-not $Process.HasExited) {
        $st = Get-CoordinatorState
        if (-not $st -or $st.state -ne 'HEALTH_CHECKING') { break }
        if ((Get-Service RoofSpanRelayConnector).Status -eq 'Running') { Stop-Service RoofSpanRelayConnector -Force; $stops++ }
        Start-Sleep -Milliseconds 250
    }
    Assert-True 'fault: Relay connector stopped while the coordinator was HEALTH_CHECKING' ($stops -gt 0) "stops=$stops"
}

# -- scenarios -----------------------------------------------------------------------------------------------------
$Scenarios = @{
    'clean-install-no-postgres' = {
        Step-CleanMachine
        Install-N
        Assert-True 'real EDB prerequisite executed' ((Get-BurnLog 'install-n') -match 'Applied execute package: PostgreSQLPrereq, result: 0x0') ''
        Set-Layer 'environment'; New-Sentinel; $before = Get-Manifest 'before'
        Restart-Service RoofSpanBackend -Force
        Assert-RerunPreserves $before 'restart' @('sentinel', 'config_sha256', 'identity_sha256') | Out-Null
        Write-Assertion 'outcome:success' $true 'clean machine -> healthy Office with real EDB'
    }
    'clean-install-offline' = {
        Step-CleanMachine
        Block-Internet
        Install-N 'install-offline'
        Unblock-Internet
        Write-Assertion 'outcome:success' $true 'installed and healthy with outbound Internet blocked'
    }
    'upgrade-n1-to-n' = { $c = Start-UpgradeContext 'n1'; Complete-Upgrade $c (Start-Setup $Setup 'upgrade'); Assert-UpgradeSuccess $c }
    'upgrade-n2-to-n' = { $c = Start-UpgradeContext 'n2'; Complete-Upgrade $c (Start-Setup $Setup 'upgrade'); Assert-UpgradeSuccess $c }
    'same-version-reinstall' = {
        $before = New-SeededN
        Assert-SetupSucceeded 'reinstall' (Invoke-Setup $Setup 'reinstall')
        Assert-BurnDidNotApply 'reinstall' 'RoofSpanUpgradeCoordinator'
        Assert-RerunPreserves $before 'reinstall' | Out-Null
        Write-Assertion 'outcome:success' $true 'same-version reinstall preserved data, config and identity'
    }
    'repair-from-arp' = {
        $before = New-SeededN
        $bundle = Get-OfficeBundle
        Assert-True 'bundle registered in Add/Remove Programs with a cached setup' ($bundle -and (Test-Path $bundle.BundleCachePath)) ''
        $file = Join-Path $InstallRoot 'frontend\index.html'; $hash = Get-Sha256 $file
        Remove-Item $file -Force
        Assert-SetupSucceeded 'repair' (Invoke-Setup $bundle.BundleCachePath 'repair' @('/repair'))
        Assert-Equal 'repair restored the deleted installed file' $hash (Get-Sha256 $file)
        Assert-RerunPreserves $before 'repair' | Out-Null
        Write-Assertion 'outcome:success' $true 'ARP repair restored files and kept data'
    }
    'legacy-pg-5442-no-pgsuper' = {
        New-SeededN | Out-Null
        Set-Layer 'environment'
        Invoke-Sql 'ALTER SYSTEM SET port = 5442' 'postgres' -Super | Out-Null
        foreach ($s in $OfficeServices) { Stop-Service $s -Force }
        Restart-Service RoofSpanPostgreSQL -Force
        Wait-Until { Get-NetTCPConnection -LocalPort 5442 -State Listen -ErrorAction SilentlyContinue } 60 'PostgreSQL on 5442' | Out-Null
        (Get-Content $Cfg -Raw) -replace '@127\.0\.0\.1:5432/', '@127.0.0.1:5442/' | Set-Content -Encoding ASCII -NoNewline $Cfg
        Move-Item (Join-Path $IdentityDir 'pg_super.bin') (Join-Path $env:RUNNER_TEMP 'legacy-held-pg_super.bin') -Force
        foreach ($s in $OfficeServices) { Start-Service $s }
        Wait-OfficeHealthy -Version $B.version -BuildSha $B.git_sha
        $before = Get-Manifest 'before-legacy'
        Assert-True 'legacy layout: no pg_super.bin, DATABASE_URL on 5442' ((-not (Test-Path (Join-Path $IdentityDir 'pg_super.bin'))) -and (Get-AppDb).Port -eq 5442) ''
        $off = Get-DiagOffset
        Assert-SetupSucceeded 'legacy' (Invoke-Setup $Setup 'legacy')
        Assert-True 'prep took the legacy path' ((Get-DiagSince $off) -match 'PREP-END-SKIP-LEGACY') ''
        Assert-RerunPreserves $before 'legacy' @('sentinel', 'revisions', 'config_key_sha256', 'services', 'api_version') | Out-Null
        Assert-True 'PostgreSQL still on 5442 and nothing on 5432' ((Get-NetTCPConnection -LocalPort 5442 -State Listen -ErrorAction SilentlyContinue) -and -not (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue)) ''
        Write-Assertion 'outcome:success' $true 'legacy 5442 install preserved without a superuser credential'
    }
    'managed-pg-with-pgsuper' = {
        $before = New-SeededN
        $off = Get-DiagOffset
        Assert-SetupSucceeded 'managed' (Invoke-Setup $Setup 'managed')
        Assert-True 'prep took the managed path' ((Get-DiagSince $off) -match 'PREP-END-SKIP-MANAGED') ''
        Assert-True 'PostgreSQLVerify succeeded with the saved credential' ((Get-BurnLog 'managed') -match 'Applied execute package: PostgreSQLVerify, result: 0x0') ''
        Assert-RerunPreserves $before 'managed' | Out-Null
        Write-Assertion 'outcome:success' $true 'managed PostgreSQL reused via pg_super.bin'
    }
    'pg-service-stopped' = {
        $before = New-SeededN
        foreach ($s in $OfficeServices + 'RoofSpanPostgreSQL') { Stop-Service $s -Force }
        Assert-True 'RoofSpanPostgreSQL stopped before setup' ((Get-Service RoofSpanPostgreSQL).Status -eq 'Stopped') ''
        Assert-SetupSucceeded 'pg-stopped' (Invoke-Setup $Setup 'pg-stopped')
        Assert-True 'RoofSpanPostgreSQL running after setup' ((Get-Service RoofSpanPostgreSQL).Status -eq 'Running') ''
        Assert-RerunPreserves $before 'pg-stopped' | Out-Null
        Write-Assertion 'outcome:success' $true 'stopped PostgreSQL was started; data preserved'
    }
    'port-5432-unrelated-process' = {
        Step-CleanMachine
        $holder = Start-PortHolder 5432
        $off = Get-DiagOffset
        $code = Invoke-Setup $Setup 'port-busy'
        Assert-SafeStopNoInstall 'port-busy' $code
        Assert-True 'actionable port-in-use stop recorded' ((Get-DiagSince $off) -match 'PREP-STOP: TCP port 5432 is already in use') ''
        Assert-True 'unrelated listener untouched' ((-not $holder.HasExited) -and (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $holder.Id })) ''
        Write-Assertion 'outcome:safe_stop' $true 'stopped before PostgreSQL/Office installation'
    }
    'unrelated-postgres-service' = {
        Step-CleanMachine
        $pw = 'Unrel!' + [guid]::NewGuid().ToString('N'); Register-Secret $pw
        Install-EdbFixture 'postgresql-x64-16-unrelated' 5432 'C:\UnrelatedPG\16' 'C:\UnrelatedPG\data' $pw
        $psql = 'C:\UnrelatedPG\16\bin\psql.exe'
        $q = { param($sql) $env:PGPASSWORD = $pw; try { (& $psql -X -A -t -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U postgres -d postgres -c $sql 2>&1 | Out-String).Trim() } finally { Remove-Item Env:\PGPASSWORD } }
        & $q "CREATE TABLE other_app_sentinel AS SELECT g, md5(g::text) v FROM generate_series(1,250) g" | Out-Null
        $digest = & $q "SELECT md5(string_agg(g || v, ',' ORDER BY g)) FROM other_app_sentinel"
        $svcBefore = Get-CimInstance Win32_Service -Filter "Name='postgresql-x64-16-unrelated'" | ForEach-Object { "$($_.PathName)|$($_.StartMode)|$($_.State)" }
        $conf = Get-Sha256 'C:\UnrelatedPG\data\postgresql.conf'
        $code = Invoke-Setup $Setup 'unrelated-pg'
        Assert-SafeStopNoInstall 'unrelated-pg' $code
        Assert-Equal 'unrelated service untouched' $svcBefore (Get-CimInstance Win32_Service -Filter "Name='postgresql-x64-16-unrelated'" | ForEach-Object { "$($_.PathName)|$($_.StartMode)|$($_.State)" })
        Assert-Equal 'unrelated postgresql.conf untouched' $conf (Get-Sha256 'C:\UnrelatedPG\data\postgresql.conf')
        Assert-Equal 'unrelated database data untouched' $digest (& $q "SELECT md5(string_agg(g || v, ',' ORDER BY g)) FROM other_app_sentinel")
        Write-Assertion 'outcome:safe_stop' $true 'another application''s PostgreSQL was not modified'
    }
    'stale-config-no-cluster' = {
        Step-CleanMachine
        New-Item -ItemType Directory -Force (Split-Path $Cfg), $IdentityDir | Out-Null
        $stalePw = 'Stale' + [guid]::NewGuid().ToString('N'); $staleJwt = [guid]::NewGuid().ToString('N') + 'jwt'
        Register-Secret $stalePw; Register-Secret $staleJwt
        Set-Content -Encoding ASCII $Cfg @("DATABASE_URL=postgresql+asyncpg://roofspan:$stalePw@127.0.0.1:5432/roofspan", "JWT_SECRET=$staleJwt")
        Add-Type -AssemblyName System.Security
        [IO.File]::WriteAllBytes((Join-Path $IdentityDir 'pg_super.bin'), [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($stalePw), $null, 'LocalMachine'))
        $hCfg = Get-Sha256 $Cfg; $hBin = Get-Sha256 (Join-Path $IdentityDir 'pg_super.bin')
        $off = Get-DiagOffset
        Install-N 'stale-no-cluster'
        Assert-True 'prep archived the stale files' ((Get-DiagSince $off) -match 'PREP-RECLAIM-STALE-LEFTOVERS') ''
        $arch = @(Get-ChildItem $Data -Directory -Filter 'reclaimed-*')[-1]
        Assert-Equal 'stale roofspan.env archived byte-identical' $hCfg (Get-Sha256 (Join-Path $arch.FullName 'roofspan.env'))
        Assert-Equal 'stale pg_super.bin archived byte-identical' $hBin (Get-Sha256 (Join-Path $arch.FullName 'pg_super.bin'))
        Assert-True 'fresh configuration replaced the stale one' ((Get-Sha256 $Cfg) -ne $hCfg) ''
        Write-Assertion 'outcome:success' $true 'stale leftovers archived (never deleted); fresh install healthy'
    }
    'stale-config-real-cluster' = {
        $before = New-SeededN
        $svc = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
        $data = [regex]::Match($svc.PathName, '-D\s+"([^"]+)"').Groups[1].Value
        Assert-True 'located the real cluster data directory' (Test-Path (Join-Path $data 'PG_VERSION')) $data
        foreach ($s in $OfficeServices + 'RoofSpanPostgreSQL') { Stop-Service $s -Force }
        $ctl = Get-Sha256 (Join-Path $data 'global\pg_control')
        & sc.exe delete RoofSpanPostgreSQL | Out-Null
        Wait-Until { -not (Get-Service RoofSpanPostgreSQL -ErrorAction SilentlyContinue) } 60 'service unregistered' | Out-Null
        $off = Get-DiagOffset
        $code = Invoke-Setup $Setup 'stale-cluster'
        Set-Layer 'prerequisite'
        Assert-True 'setup stopped (non-zero exit)' ($code -notin 0, 3010) "exit=$code"
        Assert-True 'actionable missing-service stop recorded' ((Get-DiagSince $off) -match "PREP-STOP: An existing RoofSpan configuration") ''
        Assert-BurnDidNotApply 'stale-cluster' 'PostgreSQLPrereq'
        Assert-BurnDidNotApply 'stale-cluster' 'RoofSpanOfficeMsi'
        Assert-Equal 'cluster control file untouched' $ctl (Get-Sha256 (Join-Path $data 'global\pg_control'))
        Assert-Equal 'configuration untouched' $before.config_sha256 (Get-Sha256 $Cfg)
        Set-Layer 'recovery'
        & sc.exe create RoofSpanPostgreSQL binPath= "$($svc.PathName)" start= auto obj= "$($svc.StartName)" | Out-Null
        Start-Service RoofSpanPostgreSQL; foreach ($s in $OfficeServices) { Start-Service $s }
        Wait-OfficeHealthy -Version $B.version -BuildSha $B.git_sha
        Assert-Equal 'customer data intact once the service is restored' $before.sentinel (Get-Manifest 'after-reregister').sentinel
        Write-Assertion 'outcome:safe_stop' $true 'refused to create a replacement database over existing data'
    }
    'pg-non-default-location' = {
        New-SeededN | Out-Null
        $svc = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
        $exe = [regex]::Match($svc.PathName, '^"([^"]+)"').Groups[1].Value
        $root = Split-Path (Split-Path $exe)
        foreach ($s in $OfficeServices + 'RoofSpanPostgreSQL') { Stop-Service $s -Force }
        $newRoot = 'D:\rs-custom\pg16'
        New-Item -ItemType Directory -Force (Split-Path $newRoot) | Out-Null
        & robocopy.exe $root $newRoot /E /COPYALL /NFL /NDL /NJH /NJS | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
        Move-Item $root 'C:\rs-original-pg-moved' -Force
        & icacls.exe 'D:\rs-custom' /grant "*S-1-5-20:(OI)(CI)F" | Out-Null
        & sc.exe config RoofSpanPostgreSQL binPath= ($svc.PathName.Replace($root, $newRoot)) | Out-Null
        Start-Service RoofSpanPostgreSQL; foreach ($s in $OfficeServices) { Start-Service $s }
        Wait-OfficeHealthy -Version $B.version -BuildSha $B.git_sha
        $before = Get-Manifest 'before-relocated'
        Assert-True 'PostgreSQL now runs from a non-default location' ((Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'").PathName -like "*$newRoot*") ''
        Assert-SetupSucceeded 'relocated' (Invoke-Setup $Setup 'relocated')
        Assert-RerunPreserves $before 'relocated' | Out-Null
        Write-Assertion 'outcome:success' $true 'non-default binary/data location honored'
    }
    'corrupt-saved-credential' = {
        $before = New-SeededN
        $bin = Join-Path $IdentityDir 'pg_super.bin'
        $junk = New-Object byte[] 256; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($junk); [IO.File]::WriteAllBytes($bin, $junk)
        $hBad = Get-Sha256 $bin
        $code = Invoke-Setup $Setup 'corrupt-cred'
        Set-Layer 'prerequisite'
        Assert-Equal 'corrupt credential never silently overwritten' $hBad (Get-Sha256 $bin)
        Assert-Equal 'configuration untouched' $before.config_sha256 (Get-Sha256 $Cfg)
        if ($code -in 0, 3010) {
            Assert-RerunPreserves $before 'corrupt-cred' @('sentinel', 'config_sha256', 'revisions', 'office_msi_version') | Out-Null
            Write-Assertion 'outcome:safe_stop_or_success' $true 'branch=success: setup completed using the application credential'
        } else {
            Assert-BurnDidNotApply 'corrupt-cred' 'RoofSpanOfficeMsi'
            Assert-OfficeServicesRunning 'corrupt-cred'
            Wait-OfficeHealthy -Version $B.version -BuildSha $B.git_sha
            Assert-Equal 'customer data intact' $before.sentinel (Get-Manifest 'after-corrupt-cred').sentinel
            Write-Assertion 'outcome:safe_stop_or_success' $true "branch=safe_stop: exit=$code before Office changed"
        }
    }
    'insufficient-backup-disk' = {
        $c = Start-UpgradeContext 'n1'
        Mount-TinyVolume (Join-Path $Data 'upgrade-backups') 64
        Complete-Upgrade $c (Start-Setup $Setup 'upgrade')
        Invoke-Cleanups
        Assert-UpgradeSafeStop $c
        Assert-True 'reported insufficient disk space' ("$($c.State.error)" -match 'not enough free disk space') ''
    }
    'pg-dump-failure' = {
        $c = Start-UpgradeContext 'n1'
        Add-DenyAce (Join-Path (Get-PgBin) 'pg_dump.exe') 'RX'
        Complete-Upgrade $c (Start-Setup $Setup 'upgrade')
        Invoke-Cleanups
        Assert-True 'failure occurred while BACKING_UP' ($c.History -contains 'BACKING_UP' -and $c.History -notcontains 'BACKUP_VERIFIED') ($c.History -join '>')
        Assert-UpgradeSafeStop $c
    }
    'backup-verification-failure' = {
        $c = Start-UpgradeContext 'n1'
        Add-DenyAce (Join-Path (Get-PgBin) 'pg_restore.exe') 'RX'
        Complete-Upgrade $c (Start-Setup $Setup 'upgrade')
        Invoke-Cleanups
        Assert-True 'dump was written before verification failed' (Test-Path (Join-Path "$($c.State.backup_dir)" 'roofspan.dump')) ''
        Assert-True 'verification never reached BACKUP_VERIFIED' ($c.History -notcontains 'BACKUP_VERIFIED') ($c.History -join '>')
        Assert-UpgradeSafeStop $c
    }
    'installer-failure-after-backup' = {
        $c = Start-UpgradeContext 'n1'
        Add-DenyAce (Join-Path $InstallRoot 'services\roofspan-backend\roofspan-backend.exe') 'W,D'
        Complete-Upgrade $c (Start-Setup $Setup 'upgrade')
        Invoke-Cleanups
        Assert-True 'failed in INSTALLING after BACKUP_VERIFIED' (($c.History -contains 'BACKUP_VERIFIED') -and ($c.History -notcontains 'MIGRATING')) ($c.History -join '>')
        Assert-UpgradeRollback $c
    }
    'migration-failure-before-revision' = {
        $c = Start-UpgradeContext 'n1' -NeedsPending -NeedsSuper
        $p = Start-Setup $Setup 'upgrade'
        Wait-CoordinatorState @('INSTALLING') 3600 $p | Out-Null
        Enable-MigrationFault 'first'
        Complete-Upgrade $c $p
        $f = Get-MigrateFault $c
        Assert-True 'failed before any DDL or revision write' ($f.Ddl -eq 0) "ddl=$($f.Ddl) point=$($f.Point)"
        $failedRev = Invoke-Sql 'SELECT string_agg(version_num, '','' ORDER BY version_num) FROM alembic_version' "roofspan_failed_$($c.State.attempt_id)" -Super
        Assert-Equal 'no revision was applied in the failed database' $c.Before.revisions.business $failedRev
        Assert-UpgradeRollback $c
    }
    'migration-failure-partial' = {
        $c = Start-UpgradeContext 'n1' -NeedsPending -NeedsSuper
        $p = Start-Setup $Setup 'upgrade'
        Wait-CoordinatorState @('INSTALLING') 3600 $p | Out-Null
        Enable-MigrationFault 'final-head'
        Complete-Upgrade $c $p
        $f = Get-MigrateFault $c
        if ($f.Ddl -eq 0) { throw "BLOCKED_NO_PENDING_MIGRATION: N's pending revisions over baseline n1 executed no DDL before the final head" }
        Assert-True 'schema changes were applied before the failure' ($f.Ddl -gt 0) "ddl=$($f.Ddl) point=$($f.Point)"
        Assert-UpgradeRollback $c
    }
    'backend-startup-failure' = {
        $c = Start-UpgradeContext 'n1'
        $p = Start-Setup $Setup 'upgrade'
        Wait-CoordinatorState @('INSTALLING') 3600 $p | Out-Null
        Wait-Until { -not (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) } 120 'port 8001 free' | Out-Null
        $holder = Start-PortHolder 8001
        Write-Assertion 'fault armed: port 8001 held exclusively' $true ''
        Wait-CoordinatorState @('RESTORING', 'ROLLED_BACK', 'FAILED', 'COMPLETE') 7200 $p | Out-Null
        Stop-Process -Id $holder.Id -Force
        Complete-Upgrade $c $p
        Assert-True 'failure occurred at STARTING/HEALTH_CHECKING after migration' (($c.History -contains 'STARTING') -and ($c.History -contains 'MIGRATING')) ($c.History -join '>')
        Assert-UpgradeRollback $c
    }
    'health-check-failure' = {
        $c = Start-UpgradeContext 'n1'
        $p = Start-Setup $Setup 'upgrade'
        Watch-RelayDuringHealth $p
        Complete-Upgrade $c $p
        Assert-True 'health check reported the Relay failure' ("$($c.State.error)" -match 'RoofSpanRelayConnector') ''
        Assert-UpgradeRollback $c
    }
    'database-restore-failure' = {
        $c = Start-UpgradeContext 'n1' -NeedsSuper
        $p = Start-Setup $Setup 'upgrade'
        Wait-CoordinatorState @('INSTALLING') 3600 $p | Out-Null
        $restoreExe = Join-Path (Get-PgBin) 'pg_restore.exe'
        Add-DenyAce $restoreExe 'RX'
        Watch-RelayDuringHealth $p
        Complete-Upgrade $c $p
        Remove-DenyAce $restoreExe
        Set-Layer 'recovery'
        Assert-True 'setup reported failure' ($c.Code -notin 0, 3010) "exit=$($c.Code)"
        Assert-True 'coordinator FAILED (manual recovery required)' ($c.State.state -eq 'FAILED' -and "$($c.State.recovery_error)") "state=$($c.State.state)"
        $bm = Get-Content (Join-Path $c.State.backup_dir 'manifest.json') -Raw | ConvertFrom-Json
        Assert-True 'verified backup manifest retained for this attempt' ($bm.verified -eq $true -and $bm.attempt_id -eq $c.State.attempt_id) ''
        foreach ($d in $bm.databases) { Assert-Equal "dump of $($d.name) intact" $d.sha256 (Get-Sha256 $d.file) }
        $status = (& (Join-Path $Data 'upgrade\bin\roofspan-upgrade.exe') status | Select-Object -Last 1) | ConvertFrom-Json
        Assert-Equal 'roofspan-upgrade status reports FAILED' 'FAILED' $status.state
        $scratch = 'rs_matrix_manual_restore'
        Invoke-Sql "CREATE DATABASE $scratch TEMPLATE template0" 'postgres' -Super | Out-Null
        $env:PGPASSWORD = Get-SuperPassword
        try { & $restoreExe -h 127.0.0.1 -p (Get-AppDb).Port -U postgres -d $scratch --exit-on-error (@($bm.databases | Where-Object { $_.name -eq 'roofspan' })[0].file) 2>&1 | Out-Null; $rc = $LASTEXITCODE }
        finally { Remove-Item Env:\PGPASSWORD }
        Assert-True 'manual restore from the retained backup succeeded' ($rc -eq 0) "pg_restore exit=$rc"
        Assert-Equal 'manual restore contains the exact sentinel data' $c.Before.sentinel.business (Get-SentinelDigest $scratch)
        Write-Assertion 'outcome:failed_backup_retained' $true 'recovery failed loudly; verified backup retained and proven restorable'
    }
    'interrupted-upgrade-retry' = {
        $c = Start-UpgradeContext 'n1'
        $p = Start-Setup $Setup 'upgrade-interrupted'
        $st = Wait-CoordinatorState @('INSTALLING') 3600 $p
        Get-Process roofspan-upgrade, RoofSpanSetup -ErrorAction SilentlyContinue | Stop-Process -Force
        Write-Assertion 'fault: coordinator + Burn killed during INSTALLING (simulated power loss)' $true "attempt=$($st.attempt_id)"
        Wait-Until { -not (Get-Process roofspan-upgrade, RoofSpanSetup -ErrorAction SilentlyContinue) -and -not (Test-MsiBusy) } 1800 'killed processes gone and Windows Installer idle' | Out-Null
        Copy-Item $StateFile (Get-EvidencePath 'state-interrupted.json') -Force
        Assert-True 'interrupted attempt left a non-terminal durable state' ((Get-CoordinatorState).state -notin 'COMPLETE', 'ROLLED_BACK', 'FAILED') "state=$((Get-CoordinatorState).state)"
        Complete-Upgrade $c (Start-Setup $Setup 'retry') 'retry'
        $journal = Get-Content (Join-Path $Data 'upgrade\journal.log') | ForEach-Object { $_ | ConvertFrom-Json }
        Assert-True 'retry recovered the interrupted attempt first' (@($journal | Where-Object { $_.attempt -eq $st.attempt_id -and $_.state -eq 'ROLLED_BACK' }).Count -ge 1) ''
        Assert-True 'retry ran a new attempt' ($c.State.attempt_id -ne $st.attempt_id) ''
        Assert-UpgradeSuccess $c 'retry' 'success_after_retry'
    }
    'pending-reboot' = {
        Step-CleanMachine
        $sm = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
        New-Item -ItemType Directory -Force 'C:\rs-pending' | Out-Null; Set-Content 'C:\rs-pending\a.tmp' 'x'
        $prior = (Get-ItemProperty $sm -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
        Set-ItemProperty $sm -Name PendingFileRenameOperations -Type MultiString -Value (@($prior) + @('\??\C:\rs-pending\a.tmp', '') | Where-Object { $_ -ne $null })
        New-Item 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending' -Force | Out-Null
        Assert-True 'reboot is pending before setup' (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') ''
        Install-N 'pending-reboot'
        Write-Assertion 'outcome:success' $true 'clean install completed with pending-reboot markers present'
    }
    'silent-install' = {
        Step-CleanMachine
        $media = 'C:\Install Media\RoofSpan Setup (x64)'; New-Item -ItemType Directory -Force $media | Out-Null
        Copy-Item $Setup (Join-Path $media 'RoofSpanSetup.exe')
        Assert-Equal 'copied media is the tested artifact' $ExpectedSha256 (Get-Sha256 (Join-Path $media 'RoofSpanSetup.exe'))
        Install-N 'silent' (Join-Path $media 'RoofSpanSetup.exe')
        Assert-True 'no setup process left running' (Wait-Until { -not (Get-Process RoofSpanSetup -ErrorAction SilentlyContinue) } 120 'setup processes exit') ''
        Assert-True 'bundle registered with a quiet uninstall command' ((Get-OfficeBundle).QuietUninstallString) ''
        Write-Assertion 'outcome:success' $true 'silent install from a path with spaces'
    }
    'uninstall-reinstall-retained-data' = {
        $before = New-SeededN
        $bundle = Get-OfficeBundle
        $quiet = [regex]::Match($bundle.QuietUninstallString, '^"([^"]+)"\s*(.*)$')
        $u = Start-Process $quiet.Groups[1].Value -ArgumentList ($quiet.Groups[2].Value + ' /norestart /log "' + (Get-EvidencePath 'burn-uninstall.log') + '"') -Wait -PassThru
        Set-Layer 'msi'
        Assert-True 'ARP quiet uninstall succeeded' ($u.ExitCode -in 0, 3010) "exit=$($u.ExitCode)"
        Assert-True 'Office removed' (-not (Get-OfficeMsi) -and -not (Get-Service RoofSpanBackend -ErrorAction SilentlyContinue)) ''
        Assert-True 'PostgreSQL retained (permanent prerequisite)' (Get-Service RoofSpanPostgreSQL -ErrorAction SilentlyContinue) ''
        $cfgKept = Test-Path $Cfg
        Write-Assertion 'roofspan.env retained after uninstall (recorded)' $true "retained=$cfgKept"
        Assert-SetupSucceeded 'reinstall' (Invoke-Setup $Setup 'reinstall')
        $keys = @('sentinel', 'identity_sha256', 'revisions') + $(if ($cfgKept) { @('config_key_sha256') } else { @() })
        Assert-RerunPreserves $before 'reinstall' $keys | Out-Null
        Write-Assertion 'outcome:success' $true 'customer data retained across uninstall + reinstall'
    }
    'webview2-absent-offline' = {
        Step-CleanMachine
        $wvKey = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
        $pv = (Get-ItemProperty $wvKey -Name pv -ErrorAction SilentlyContinue).pv
        Assert-True 'WebView2 genuinely absent before setup' ((-not $pv -or $pv -eq '0.0.0.0') -and -not (Test-Path 'C:\Program Files (x86)\Microsoft\EdgeWebView\Application')) "pv=$pv"
        $others = @(Get-ChildItem (Split-Path $Setup) -File | Where-Object { $_.Name -ne 'RoofSpanSetup.exe' -and $_.Extension -in '.exe', '.msi', '.msu', '.cab' })
        $stray = @(Get-ChildItem $env:RUNNER_TEMP, $env:USERPROFILE -Recurse -File -Depth 3 -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)webview2.*\.exe$|postgresql-.*windows.*\.exe$' })
        Assert-True 'only RoofSpanSetup.exe is present (prerequisite source files deleted)' (($others.Count + $stray.Count) -eq 0) ((@($others) + @($stray) | ForEach-Object FullName) -join ',')
        Block-Internet
        Install-N 'webview2-offline'
        Assert-True 'embedded WebView2 installer executed' ((Get-BurnLog 'webview2-offline') -match 'Applied execute package: WebView2Runtime, result: 0x0') ''
        Assert-True 'WebView2 runtime registered after setup' ((Get-ItemProperty $wvKey -Name pv -ErrorAction SilentlyContinue).pv -notin $null, '', '0.0.0.0') ''
        $shell = Start-Process (Join-Path $InstallRoot 'shell\RoofSpanOffice.exe') -PassThru
        Add-Cleanup ([scriptblock]::Create("Stop-Process -Id $($shell.Id) -Force -ErrorAction SilentlyContinue"))
        Assert-True 'native shell window opened' (Wait-Until { $shell.Refresh(); $shell.MainWindowHandle -ne 0 } 120 'shell main window') "title=$($shell.MainWindowTitle)"
        Assert-True 'shell hosts a WebView2 child process' (Wait-Until { Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | Where-Object { $_.ParentProcessId -eq $shell.Id } } 120 'msedgewebview2 child') ''
        Unblock-Internet
        Write-Assertion 'outcome:success' $true 'WebView2 installed offline from the embedded payload; shell opened'
    }
    'uac-different-admin' = {
        Step-CleanMachine
        $cp = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System').ConsentPromptBehaviorAdmin
        Assert-True 'VM precondition: approver admin elevation is pre-approved (ConsentPromptBehaviorAdmin=0)' ($cp -eq 0) "value=$cp"
        Assert-True 'VM precondition: approver credential provided' ($env:ROOFSPAN_VM_APPROVER_USER -and $env:ROOFSPAN_VM_APPROVER_PASSWORD) ''
        Register-Secret $env:ROOFSPAN_VM_APPROVER_PASSWORD
        Assert-True 'approver differs from the interactive user' ($env:ROOFSPAN_VM_APPROVER_USER -ne $env:USERNAME) ''
        $cred = [pscredential]::new($env:ROOFSPAN_VM_APPROVER_USER, (ConvertTo-SecureString $env:ROOFSPAN_VM_APPROVER_PASSWORD -AsPlainText -Force))
        $codeFile = Join-Path $env:PUBLIC 'rs-uac-exit.txt'; Remove-Item $codeFile -ErrorAction SilentlyContinue
        $log = Get-EvidencePath 'burn-install-n.log'
        $inner = "`$p = Start-Process '$Setup' -Verb RunAs -Wait -PassThru -ArgumentList '/quiet /norestart /log `"$log`"'; Set-Content '$codeFile' `$p.ExitCode"
        Start-Process pwsh -Credential $cred -ArgumentList @('-NoProfile', '-EncodedCommand', [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))) | Out-Null
        $owner = Wait-Until { Get-CimInstance Win32_Process -Filter "Name='RoofSpanSetup.exe'" | ForEach-Object { (Invoke-CimMethod -InputObject $_ -MethodName GetOwner).User } | Where-Object { $_ } | Select-Object -First 1 } 300 'setup process owner'
        Assert-True 'setup ran under the approving administrator' ($env:ROOFSPAN_VM_APPROVER_USER -like "*$owner") "owner=$owner"
        $code = [int](Wait-Until { if (Test-Path $codeFile) { (Get-Content $codeFile).Trim() } } 5400 'elevated setup exit code' -PollMs 2000)
        Assert-SetupSucceeded 'install-n' $code
        Assert-NHealthy 'uac'
        $shell = Start-Process (Join-Path $InstallRoot 'shell\RoofSpanOffice.exe') -PassThru
        Add-Cleanup ([scriptblock]::Create("Stop-Process -Id $($shell.Id) -Force -ErrorAction SilentlyContinue"))
        Assert-True 'interactive user can open the shell' (Wait-Until { $shell.Refresh(); $shell.MainWindowHandle -ne 0 } 120 'shell window') ''
        Write-Assertion 'outcome:success' $true "approved by $($env:ROOFSPAN_VM_APPROVER_USER); used by $($env:USERNAME)"
    }
    'low-resource-large-db' = {
        $cs = Get-CimInstance Win32_ComputerSystem
        Assert-True 'VM is low-resource (<= 4.5 GB RAM, <= 2 logical CPUs)' ($cs.TotalPhysicalMemory -le 4.5GB -and $cs.NumberOfLogicalProcessors -le 2) "ram=$($cs.TotalPhysicalMemory) cpu=$($cs.NumberOfLogicalProcessors)"
        $gb = if ($env:ROOFSPAN_MATRIX_DB_GB) { [int]$env:ROOFSPAN_MATRIX_DB_GB } else { 2 }
        $c = Start-UpgradeContext 'n1'
        Invoke-Sql 'CREATE TABLE public.ci_matrix_bulk (id bigint PRIMARY KEY, payload text NOT NULL)' | Out-Null
        $chunk = 200000; $target = [long]$gb * 1GB / 1100
        for ($i = 0L; $i -lt $target; $i += $chunk) { Invoke-Sql "INSERT INTO public.ci_matrix_bulk SELECT g, repeat(md5(g::text), 32) FROM generate_series($($i + 1), $($i + $chunk)) g" | Out-Null }
        $size = [long](Invoke-Sql "SELECT pg_database_size('roofspan')")
        Assert-True "database is realistically sized (>= $gb GB)" ($size -ge ([long]$gb * 1GB * 0.9)) "bytes=$size"
        $bulkSql = "SELECT count(*) || ':' || sum(length(payload)) FROM public.ci_matrix_bulk"
        $bulk = Invoke-Sql $bulkSql
        $c.Before = Get-Manifest 'before-large'
        $t0 = Get-Date
        Complete-Upgrade $c (Start-Setup $Setup 'upgrade')
        Assert-UpgradeSuccess $c
        Assert-Equal 'bulk data preserved' $bulk (Invoke-Sql $bulkSql)
        Write-Assertion 'upgrade duration recorded' $true ("minutes={0:N1}" -f ((Get-Date) - $t0).TotalMinutes)
    }
}

# -- run ------------------------------------------------------------------------------------------------------------
$status = 'FAIL'; $reason = ''; $layer = ''
try {
    if (-not $Scenarios.ContainsKey($Scenario)) { throw "no implementation for scenario '$Scenario'" }
    Set-Layer 'build'
    Assert-Equal 'artifact is the single tested build (SHA-256)' $ExpectedSha256.ToLowerInvariant() (Get-Sha256 $Setup)
    Assert-Equal 'build record matches the artifact' $ExpectedSha256.ToLowerInvariant() "$($B.artifact_sha256)"
    Assert-Equal 'artifact is a production build (no fault injection)' $false $B.fault_injection
    & $Scenarios[$Scenario]
    $status = 'PASS'
} catch {
    $msg = Protect-Text $_.Exception.Message
    if ($msg -match '^(BLOCKED_NO_PENDING_MIGRATION|BLOCKED_MISSING_BASELINE): (.+)$') { $status = $Matches[1]; $reason = $Matches[2] }
    else { $status = 'FAIL'; $layer = Get-Layer; $reason = $msg; Write-Host "::error::$Scenario failed in layer $layer : $msg" }
} finally {
    Invoke-Cleanups
    try { Save-Diagnostics } catch { Write-Warning ('diagnostics: ' + (Protect-Text $_.Exception.Message)) }
    $env:ROOFSPAN_MATRIX_SECRETS_B64 = Get-SecretsB64
    try { & python $MatrixPy scrub --evidence $EvidenceDir; $scrubRc = $LASTEXITCODE } finally { Remove-Item Env:\ROOFSPAN_MATRIX_SECRETS_B64 }
    if ($scrubRc -ne 0) {
        Add-Content -Encoding UTF8 (Join-Path $EvidenceDir 'assertions.jsonl') '{"name":"no secrets in evidence","ok":false,"layer":"recovery","detail":"secret material found and removed; see scrub-report.json"}'
        if ($status -eq 'PASS') { $status = 'FAIL'; $layer = 'recovery'; $reason = 'secret material found in logs/evidence (removed before upload)' }
    }
    $meta = @{ artifact_sha256 = $ExpectedSha256.ToLowerInvariant(); git_sha = "$($B.git_sha)"; version = "$($B.version)"; runner = "$env:RUNNER_ENVIRONMENT"; run_id = "$env:GITHUB_RUN_ID" }
    $metaFile = Join-Path $EvidenceDir 'meta.json'; $meta | ConvertTo-Json | Set-Content -Encoding UTF8 $metaFile
    & python $MatrixPy finalize --scenario $Scenario --evidence $EvidenceDir --status $status --layer $layer --reason $reason --meta-file $metaFile
    $finalRc = $LASTEXITCODE
}
exit $finalRc
