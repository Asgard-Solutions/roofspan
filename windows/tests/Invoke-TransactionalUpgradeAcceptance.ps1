<#
  Real Windows acceptance for the transactional upgrade (disposable GitHub Actions runner ONLY).

  Precondition: N-1 (production build, version $PrevVersion) was installed with its RoofSpanSetup.exe.
  $NextSetup is a FAULT-INJECTION TEST build of version $NextVersion whose backend adds the CI-only
  migration `ci_txn_upgrade_probe` (creates table public.ci_txn_upgrade_probe).

  Scenarios (in order): unverifiable backup, forced migration failure, failed health check, interruption
  + boot-style resume (idempotent), then a successful upgrade. Every scenario checks sentinel data,
  configuration, identity files, schema revision, installed version and service health.
#>
param(
  [Parameter(Mandatory=$true)][string]$NextSetup,
  [Parameter(Mandatory=$true)][string]$PrevVersion,
  [Parameter(Mandatory=$true)][string]$NextVersion,
  [Parameter(Mandatory=$true)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This fixture may run only on the disposable GitHub Actions Windows runner.' }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$data = 'C:\ProgramData\RoofSpan'
$cfg = "$data\config\roofspan.env"
$stateFile = "$data\upgrade\state.json"
Add-Type -AssemblyName System.Security
$superPw = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
  [IO.File]::ReadAllBytes("$data\identity\pg_super.bin"), $null, [Security.Cryptography.DataProtectionScope]::LocalMachine))
$svc = Get-CimInstance Win32_Service -Filter "Name='RoofSpanPostgreSQL'"
if ($svc.PathName -notmatch '^"([^"]+)"') { throw 'unexpected PostgreSQL service path' }
$psql = Join-Path (Split-Path $Matches[1]) 'psql.exe'
$port = [regex]::Match((Get-Content $cfg -Raw), '@127\.0\.0\.1:(\d+)/').Groups[1].Value

function Sql([string]$Query, [string]$Db = 'roofspan') {
  $env:PGPASSWORD = $superPw
  try { $out = & $psql -X -A -t -h 127.0.0.1 -p $port -U postgres -d $Db -c $Query 2>&1 } finally { Remove-Item Env:\PGPASSWORD }
  if ($LASTEXITCODE -ne 0) { throw 'SQL probe failed (details withheld to protect credentials).' }
  return (($out | Out-String).Trim())
}
function Snapshot {
  [ordered]@{
    revision = Sql 'SELECT version_num FROM alembic_version'
    sentinel = Sql "SELECT md5(string_agg(id::text || ':' || payload, ',' ORDER BY id)) FROM public.ci_sentinel"
    probe_table = Sql "SELECT count(*) FROM information_schema.tables WHERE table_name='ci_txn_upgrade_probe'"
    config = (Get-FileHash $cfg).Hash
    identity = (Get-ChildItem "$data\identity" -File | Sort-Object Name | ForEach-Object { "$($_.Name)=$((Get-FileHash $_.FullName).Hash)" }) -join ';'
  }
}
function Installed-Version {
  (Invoke-RestMethod 'http://127.0.0.1:8001/api/version' -TimeoutSec 10).version
}
function Wait-Healthy([string]$Version) {
  $deadline = (Get-Date).AddSeconds(180)
  while ((Get-Date) -lt $deadline) {
    try { if ((Installed-Version) -eq $Version) { return } } catch { }
    Start-Sleep 3
  }
  throw "Office did not become healthy on version $Version"
}
function Run-Next([string]$Fault, [string]$Label) {
  $log = Join-Path $EvidenceDir "burn-$Label.log"
  if ($Fault) { $env:ROOFSPAN_UPGRADE_FAULT = $Fault } else { Remove-Item Env:\ROOFSPAN_UPGRADE_FAULT -ErrorAction SilentlyContinue }
  try { $p = Start-Process $NextSetup -ArgumentList @('/quiet', '/norestart', '/log', "`"$log`"") -Wait -PassThru }
  finally { Remove-Item Env:\ROOFSPAN_UPGRADE_FAULT -ErrorAction SilentlyContinue }
  Copy-Item $stateFile (Join-Path $EvidenceDir "state-$Label.json") -Force
  return $p.ExitCode
}
function Assert-RolledBack([hashtable]$Before, [string]$Label, [string]$ExpectState = 'ROLLED_BACK') {
  $st = Get-Content $stateFile -Raw | ConvertFrom-Json
  if ($st.state -ne $ExpectState) { throw "$Label : coordinator state $($st.state), expected $ExpectState ($($st.error))" }
  Wait-Healthy $PrevVersion
  $after = Snapshot
  foreach ($k in $Before.Keys) { if ($after[$k] -ne $Before[$k]) { throw "$Label : $k changed ($($Before[$k]) -> $($after[$k]))" } }
  foreach ($s in 'RoofSpanBackend', 'RoofSpanRelayConnector', 'RoofSpanUpdateService') {
    if ((Get-Service $s).Status -ne 'Running') { throw "$Label : $s is not running after recovery" }
  }
  Write-Host "OK [$Label]: previous version $PrevVersion, schema, data, configuration and identity restored; services healthy"
  return $st
}

# Sentinel customer data written through the N-1 application database.
Sql "CREATE TABLE IF NOT EXISTS public.ci_sentinel (id int PRIMARY KEY, payload text NOT NULL); INSERT INTO public.ci_sentinel SELECT g, 'customer-' || g || E'\\n-' || md5(g::text) FROM generate_series(1, 500) g ON CONFLICT DO NOTHING; ALTER TABLE public.ci_sentinel OWNER TO roofspan;" | Out-Null
Wait-Healthy $PrevVersion
$before = Snapshot
if ($before.probe_table -ne '0') { throw 'N-1 already has the CI probe table' }

# 1) Unverifiable backup -> stops BEFORE install or migration.
$code = Run-Next 'backup_corrupt' 'backup-corrupt'
if ($code -eq 0) { throw 'backup_corrupt: setup reported success' }
$st = Assert-RolledBack $before 'backup-corrupt'
if (@($st.history.state) -contains 'INSTALLING') { throw 'backup_corrupt: reached INSTALLING' }
if (Test-Path (Join-Path $st.backup_dir 'install-new.log')) { throw 'backup_corrupt: msiexec ran' }

# 2) Forced migration failure (schema already migrated forward) -> RESTORING -> ROLLED_BACK.
$code = Run-Next 'migration' 'migration-failure'
if ($code -eq 0) { throw 'migration: setup reported success' }
$st = Assert-RolledBack $before 'migration-failure'
if (-not (@($st.history.state) -contains 'RESTORING')) { throw 'migration: no RESTORING state' }
$failedDb = Sql "SELECT datname FROM pg_database WHERE datname = 'roofspan_failed_$($st.attempt_id)'" 'postgres'
if (-not $failedDb) { throw 'migration: the failed database was not retained (renamed)' }
$failedProbe = Sql "SELECT count(*) FROM information_schema.tables WHERE table_name='ci_txn_upgrade_probe'" $failedDb
if ($failedProbe -ne '1') { throw 'migration: the failure did not actually migrate the schema forward (test would be vacuous)' }

# 3) Failed health check -> recovery.
$code = Run-Next 'health' 'health-failure'
if ($code -eq 0) { throw 'health: setup reported success' }
Assert-RolledBack $before 'health-failure' | Out-Null

# 4) Interruption after migration (simulated power loss) -> resume (boot task command) -> ROLLED_BACK, idempotent.
$env:ROOFSPAN_UPGRADE_FAULT = 'hang_after_migration'
$log = Join-Path $EvidenceDir 'burn-interrupted.log'
$burn = Start-Process $NextSetup -ArgumentList @('/quiet', '/norestart', '/log', "`"$log`"") -PassThru
Remove-Item Env:\ROOFSPAN_UPGRADE_FAULT
$deadline = (Get-Date).AddMinutes(30)
do { Start-Sleep 5; $st = if (Test-Path $stateFile) { Get-Content $stateFile -Raw | ConvertFrom-Json } else { $null } }
while ((Get-Date) -lt $deadline -and -not ($st -and $st.state -eq 'MIGRATING' -and $st.migration.exit_code -eq 0))
if (-not ($st.state -eq 'MIGRATING')) { throw 'interruption: never reached MIGRATING' }
& schtasks.exe /Query /TN 'RoofSpan\UpgradeRecovery' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'interruption: boot recovery task is not registered' }
Get-Process roofspan-upgrade -ErrorAction SilentlyContinue | Stop-Process -Force
Stop-Process -Id $burn.Id -Force -ErrorAction SilentlyContinue
Get-Process RoofSpanSetup* -ErrorAction SilentlyContinue | Stop-Process -Force
$manifest = Join-Path $st.backup_dir 'manifest.json'
$manifestHash = (Get-FileHash $manifest).Hash
& "$data\upgrade\bin\roofspan-upgrade.exe" resume
if ($LASTEXITCODE -ne 1) { throw "interruption: resume exit $LASTEXITCODE (expected 1 = ROLLED_BACK)" }
Copy-Item $stateFile (Join-Path $EvidenceDir 'state-interrupted-resumed.json') -Force
Assert-RolledBack $before 'interrupted-resume' | Out-Null
& "$data\upgrade\bin\roofspan-upgrade.exe" resume
if ($LASTEXITCODE -ne 1) { throw 'interruption: second resume was not a no-op' }
& schtasks.exe /Query /TN 'RoofSpan\UpgradeRecovery' 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw 'interruption: recovery task was not removed after recovery' }

# 5) Successful N-1 -> N upgrade.
$code = Run-Next '' 'success'
if ($code -notin 0, 3010) { throw "success: setup exit $code" }
$st = Get-Content $stateFile -Raw | ConvertFrom-Json
if ($st.state -ne 'COMPLETE') { throw "success: state $($st.state) ($($st.error))" }
Wait-Healthy $NextVersion
$after = Snapshot
if ($after.sentinel -ne $before.sentinel) { throw 'success: sentinel data changed' }
if ($after.probe_table -ne '1') { throw 'success: new migration not applied' }
if ($after.identity -ne $before.identity) { throw 'success: identity files changed' }
$envText = Get-Content $cfg -Raw
foreach ($k in 'DATABASE_URL', 'JWT_SECRET', 'SECRETS_ENCRYPTION_KEY') {
  if (@(($envText -split "`r?`n") | Where-Object { $_ -match "^$k=" }).Count -ne 1) { throw "success: $k missing" }
}
if ((Get-FileHash $manifest).Hash -ne $manifestHash) { throw 'success: an earlier verified backup was overwritten' }
Write-Host "OK [success]: $PrevVersion -> $NextVersion preserved sentinel data, identity and configuration"

# Secrets must be absent from every log/state/evidence file.
$appPw = [Uri]::UnescapeDataString([regex]::Match($envText, 'roofspan:([^@]+)@').Groups[1].Value)
$jwt = [regex]::Match($envText, '(?m)^JWT_SECRET=(.+)$').Groups[1].Value.Trim()
$enc = [regex]::Match($envText, '(?m)^SECRETS_ENCRYPTION_KEY=(.+)$').Groups[1].Value.Trim()
Copy-Item "$data\upgrade\journal.log", "$data\logs\upgrade.log" $EvidenceDir -Force
Get-ChildItem "$data\upgrade-backups" -Recurse -Filter *.log | ForEach-Object { Copy-Item $_.FullName (Join-Path $EvidenceDir "$($_.Directory.Name)-$($_.Name)") }
foreach ($f in Get-ChildItem $EvidenceDir -File -Recurse) {
  $t = [IO.File]::ReadAllText($f.FullName)
  foreach ($s in @($superPw, $appPw, $jwt, $enc)) { if ($s -and $t.Contains($s)) { throw "secret leaked into $($f.Name)" } }
}
if (Get-ChildItem "$data\upgrade-backups" -Recurse -Filter pgpass.conf) { throw 'a PGPASSFILE was left behind' }
$acl2 = (Get-Acl $st.backup_dir).Access | Where-Object { $_.IdentityReference -match 'Users|Everyone|Authenticated' }
if ($acl2) { throw 'backup directory is readable by ordinary local users' }
Write-Host 'OK: no secrets in logs/state/evidence; backups restricted to SYSTEM + Administrators'
