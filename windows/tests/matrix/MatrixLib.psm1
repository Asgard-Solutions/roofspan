<#
  RoofSpan installer failure-matrix harness library. DESTRUCTIVE: used only after matrix.py guard approved a
  disposable GitHub-hosted runner or an approved single-use VM. Never import this on a customer machine.
  Evidence never contains secret values: secrets are registered (and masked in GitHub logs), only hashes are
  recorded, and matrix.py scrub deletes and fails on anything that still matches.
#>
$ErrorActionPreference = 'Stop'
$script:Data = 'C:\ProgramData\RoofSpan'
$script:InstallRoot = 'C:\Program Files\RoofSpan Office'
$script:Cfg = "$script:Data\config\roofspan.env"
$script:IdentityDir = "$script:Data\identity"
$script:StateFile = "$script:Data\upgrade\state.json"
$script:Api = 'http://127.0.0.1:8001'
$script:Layer = 'environment'
$script:Evidence = $null
$script:Secrets = [System.Collections.Generic.List[string]]::new()
$script:Cleanups = [System.Collections.Generic.List[scriptblock]]::new()
$script:SentinelToken = $null
$script:Started = Get-Date
$script:EdbUrl = 'https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe'
$script:EdbSha256 = 'f4bf0ac4b33471f18aad7d1d9cc52613003f3a3a612aae167366bf7f7840b2bc'
$script:OfficeServices = @('RoofSpanBackend', 'RoofSpanRelayConnector', 'RoofSpanUpdateService')

# -- evidence, assertions, layers, polling ----------------------------------------------------------------
function Initialize-Matrix([string]$EvidenceDir) {
    $script:Evidence = $EvidenceDir
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    Set-Content -Encoding UTF8 -Path (Join-Path $EvidenceDir 'assertions.jsonl') -Value $null
}
function Get-EvidencePath([string]$Name) { Join-Path $script:Evidence $Name }
function Set-Layer([string]$Name) { $script:Layer = $Name; Write-Host "---- layer: $Name" }
function Get-Layer { $script:Layer }

function Protect-Text([string]$Text) {
    if (-not $Text) { return $Text }
    foreach ($s in $script:Secrets) { $Text = $Text.Replace($s, '***') }
    return [regex]::Replace($Text, '(postgres(?:ql)?(?:\+asyncpg)?://[^:/@\s]+:)[^@\s]+@', '$1***@')
}

function Write-Assertion([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $line = [ordered]@{ name = $Name; ok = $Ok; layer = $script:Layer; detail = (Protect-Text $Detail); utc = (Get-Date).ToUniversalTime().ToString('o') }
    Add-Content -Encoding UTF8 -Path (Get-EvidencePath 'assertions.jsonl') -Value ($line | ConvertTo-Json -Compress)
    if ($Ok) { Write-Host "  PASS  $Name $($line.detail)" } else { throw "ASSERTION FAILED [$Name] $($line.detail)" }
}
function Assert-True([string]$Name, $Condition, [string]$Detail = '') { Write-Assertion $Name ([bool]$Condition) $Detail }
function Assert-Equal([string]$Name, $Expected, $Actual) {
    $e = ($Expected | ConvertTo-Json -Compress -Depth 6); $a = ($Actual | ConvertTo-Json -Compress -Depth 6)
    Write-Assertion $Name ($e -eq $a) ("expected=$e actual=$a")
}

function Wait-Until([scriptblock]$Condition, [int]$TimeoutSec, [string]$What, [int]$PollMs = 500) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $value = $null
        try { $value = & $Condition } catch { if ($_.Exception.Message -like 'ABORT:*') { throw }; $value = $null }
        if ($value) { return $value }
        Start-Sleep -Milliseconds $PollMs
    } while ((Get-Date) -lt $deadline)
    throw "timed out after $TimeoutSec s waiting for: $What"
}

function Register-Secret([string]$Value) {
    if ([string]::IsNullOrEmpty($Value) -or $Value.Length -lt 6 -or $script:Secrets.Contains($Value)) { return }
    $script:Secrets.Add($Value)
    if ($env:GITHUB_ACTIONS -eq 'true') { Write-Host "::add-mask::$Value" }
}
function Get-SecretsB64 { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json @($script:Secrets) -Compress))) }
function Add-Cleanup([scriptblock]$Action) { $script:Cleanups.Insert(0, $Action) }
function Invoke-Cleanups {
    foreach ($c in @($script:Cleanups)) { try { & $c } catch { Write-Warning ("cleanup: " + (Protect-Text $_.Exception.Message)) } }
    $script:Cleanups.Clear()
}

# -- configuration + credentials (values never written anywhere) ------------------------------------------
function Get-EnvMap([string]$Path = $script:Cfg) {
    $map = [ordered]@{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($l in (Get-Content $Path)) {
        if ($l -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') { $map[$Matches[1]] = $Matches[2].Trim() }
    }
    return $map
}
function Get-AppDb {
    $url = (Get-EnvMap)['DATABASE_URL']
    if (-not $url) { throw 'roofspan.env has no DATABASE_URL' }
    $m = [regex]::Match($url, '^postgresql(?:\+asyncpg)?://([^:]+):([^@]*)@([^:/]+):(\d+)/([^?]+)')
    if (-not $m.Success) { throw 'DATABASE_URL is not a PostgreSQL URL' }
    $pw = [Uri]::UnescapeDataString($m.Groups[2].Value)
    Register-Secret $m.Groups[2].Value; Register-Secret $pw
    return @{ User = [Uri]::UnescapeDataString($m.Groups[1].Value); Password = $pw; Host = $m.Groups[3].Value; Port = [int]$m.Groups[4].Value; Db = $m.Groups[5].Value }
}
function Register-ConfigSecrets {
    $map = Get-EnvMap
    foreach ($k in $map.Keys) { if ($k -match 'PASSWORD|SECRET|KEY|TOKEN') { Register-Secret $map[$k] } }
    if ($map['DATABASE_URL']) { Get-AppDb | Out-Null }
    Get-SuperPassword | Out-Null
}
function Get-SuperPassword {
    $bin = Join-Path $script:IdentityDir 'pg_super.bin'
    if (-not (Test-Path $bin)) { return $null }
    try {
        Add-Type -AssemblyName System.Security
        $pw = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect(
            [IO.File]::ReadAllBytes($bin), $null, [Security.Cryptography.DataProtectionScope]::LocalMachine))
    } catch { return $null }
    Register-Secret $pw
    return $pw
}
function Get-PgBin([string]$Service = 'RoofSpanPostgreSQL') {
    $svc = Get-CimInstance Win32_Service -Filter "Name='$Service'"
    if (-not $svc -or $svc.PathName -notmatch '^"?([^"]*pg_ctl\.exe)"?') { throw "$Service is not a pg_ctl service" }
    return (Split-Path $Matches[1])
}

function Invoke-Sql([string]$Query, [string]$Db = 'roofspan', [switch]$Super, [int]$Port = 0, [switch]$AsFile) {
    $app = Get-AppDb
    if ($Super) {
        $user = 'postgres'; $pw = Get-SuperPassword
        if (-not $pw) { throw 'a superuser query was required but pg_super.bin is absent or undecryptable' }
    } else { $user = $app.User; $pw = $app.Password }
    if ($Port -eq 0) { $Port = $app.Port }
    $psql = Join-Path (Get-PgBin) 'psql.exe'
    $env:PGPASSWORD = $pw; $env:PGCONNECT_TIMEOUT = '10'
    $sqlArgs = @('-c', $Query)
    if ($AsFile) {
        $f = Join-Path $env:RUNNER_TEMP ("rs-sql-" + [guid]::NewGuid().ToString('N') + '.sql')
        [IO.File]::WriteAllText($f, $Query, [Text.UTF8Encoding]::new($false)); $sqlArgs = @('-f', $f)
    }
    try { $out = & $psql -X -A -t -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port -U $user -d $Db @sqlArgs 2>&1; $rc = $LASTEXITCODE }
    finally { Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue; if ($AsFile) { Remove-Item $f -Force -ErrorAction SilentlyContinue } }
    $text = (($out | ForEach-Object { "$_" }) -join "`n").Trim()
    if ($rc -ne 0) { throw ("SQL failed on $Db (exit $rc): " + (Protect-Text $text)) }
    return $text
}

# -- sentinels + state manifests ----------------------------------------------------------------------------
function New-Sentinel([int]$Rows = 500) {
    $script:SentinelToken = ('{0}-{1}-{2}' -f $env:GITHUB_RUN_ID, $env:ROOFSPAN_MATRIX_SCENARIO, [guid]::NewGuid().ToString('N'))
    $t = $script:SentinelToken
    $ddl = "CREATE TABLE IF NOT EXISTS public.ci_matrix_sentinel (token text NOT NULL, seq int NOT NULL, payload text NOT NULL, PRIMARY KEY (token, seq));"
    $ins = "INSERT INTO public.ci_matrix_sentinel SELECT '$t', g, 'customer-' || g || chr(10) || md5('$t' || g) || ' ' || chr(220) || chr(241) || chr(8364) FROM generate_series(1, $Rows) g;"
    Invoke-Sql ($ddl + $ins) | Out-Null
    if (Test-ControlPlaneDb) { Invoke-Sql ($ddl + $ins) 'roofspan_control_plane' | Out-Null }
    Write-Host "seeded sentinel token $t ($Rows rows per database)"
}
function Test-ControlPlaneDb {
    try { return ((Invoke-Sql "SELECT count(*) FROM pg_database WHERE datname='roofspan_control_plane'" 'roofspan') -eq '1') } catch { return $false }
}
function Get-SentinelDigest([string]$Db = 'roofspan') {
    $t = $script:SentinelToken
    if (-not $t) { return 'unseeded' }
    try { return Invoke-Sql "SELECT count(*) || ':' || coalesce(md5(string_agg(seq::text || ':' || payload, ',' ORDER BY seq)), '') FROM public.ci_matrix_sentinel WHERE token = '$t'" $Db }
    catch { return 'unreadable: ' + $_.Exception.Message }
}
function Get-Revision([string]$Db, [string]$Schema = 'public') {
    try { $r = Invoke-Sql "SELECT coalesce(string_agg(version_num, ',' ORDER BY version_num), 'empty') FROM `"$Schema`".alembic_version" $Db; return $r }
    catch { return 'absent' }
}
function Get-Sha256([string]$Path) { if (Test-Path $Path -PathType Leaf) { (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant() } else { 'absent' } }
function Get-TextSha256([string]$Text) { (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($Text))) -Algorithm SHA256).Hash.ToLowerInvariant() }

function Get-UninstallEntries {
    $keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { $_.PSObject.Properties['DisplayName'] -and $_.DisplayName -match 'RoofSpan' }
}
function Get-OfficeMsi { @(Get-UninstallEntries | Where-Object { $_.PSObject.Properties['WindowsInstaller'] -and $_.WindowsInstaller -eq 1 }) | Select-Object -First 1 }
function Get-OfficeBundle { @(Get-UninstallEntries | Where-Object { $_.PSObject.Properties['BundleCachePath'] }) | Select-Object -First 1 }
function Get-ApiVersion {
    try { $v = Invoke-RestMethod "$script:Api/api/version" -TimeoutSec 5; return "$($v.version)/$($v.build_sha)" } catch { return 'unreachable' }
}
function Get-BuildInfo([string]$Service) {
    $exe = Join-Path $script:InstallRoot "services\$Service\$Service.exe"
    if (-not (Test-Path $exe)) { return 'absent' }
    $line = @(& $exe --build-info 2>$null) | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
    if (-not $line) { return 'no-build-info' }
    $bi = $line | ConvertFrom-Json
    return "$($bi.version)/$($bi.build_sha)/fault_injection=$($bi.fault_injection)"
}
function Get-CoordinatorState {
    if (-not (Test-Path $script:StateFile)) { return $null }
    try { return (Get-Content $script:StateFile -Raw | ConvertFrom-Json) } catch { return $null }
}

function Get-Manifest([string]$Label) {
    $map = Get-EnvMap
    $keyHashes = [ordered]@{}
    foreach ($k in 'DATABASE_URL', 'JWT_SECRET', 'SECRETS_ENCRYPTION_KEY') { $keyHashes[$k] = if ($map[$k]) { Get-TextSha256 $map[$k] } else { 'absent' } }
    $identity = [ordered]@{}
    if (Test-Path $script:IdentityDir) {
        Get-ChildItem $script:IdentityDir -File | Sort-Object Name | ForEach-Object { $identity[$_.Name] = Get-Sha256 $_.FullName }
    }
    $services = @(Get-CimInstance Win32_Service | Where-Object { $_.Name -like 'RoofSpan*' -or $_.Name -like '*postgres*' } |
        Sort-Object Name | ForEach-Object { "$($_.Name)|$($_.PathName)|$($_.StartMode)" })
    $states = [ordered]@{}
    Get-CimInstance Win32_Service | Where-Object { $_.Name -like 'RoofSpan*' } | Sort-Object Name | ForEach-Object { $states[$_.Name] = "$($_.State)" }
    $cpDb = Test-ControlPlaneDb
    $st = Get-CoordinatorState
    $msi = Get-OfficeMsi
    $m = [ordered]@{
        label = $Label; utc = (Get-Date).ToUniversalTime().ToString('o')
        office_msi_version = if ($msi) { "$($msi.DisplayVersion)" } else { 'absent' }
        api_version = Get-ApiVersion
        backend_build_info = Get-BuildInfo 'roofspan-backend'
        revisions = [ordered]@{
            business = Get-Revision 'roofspan'
            control_plane = if ($cpDb) { Get-Revision 'roofspan_control_plane' } else { Get-Revision 'roofspan' 'roofspan_control_plane' }
        }
        services = $services; service_states = $states
        config_sha256 = Get-Sha256 $script:Cfg; config_key_sha256 = $keyHashes; identity_sha256 = $identity
        sentinel = [ordered]@{ business = Get-SentinelDigest 'roofspan'; control_plane = if ($cpDb) { Get-SentinelDigest 'roofspan_control_plane' } else { 'n/a' } }
        coordinator = if ($st) { "$($st.attempt_id)/$($st.state)" } else { 'none' }
    }
    $m | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Get-EvidencePath "manifest-$Label.json")
    return $m
}
function Assert-ManifestKeys($Before, $After, [string[]]$Keys, [string]$Label) {
    foreach ($k in $Keys) { Assert-Equal "$Label preserves $k" $Before[$k] $After[$k] }
}

# -- setup execution ------------------------------------------------------------------------------------------
function Start-Setup([string]$Exe, [string]$Label, [string[]]$Extra = @()) {
    $log = Get-EvidencePath "burn-$Label.log"
    $args_ = @('/quiet', '/norestart', '/log', "`"$log`"") + $Extra
    Write-Host "running $Exe $($args_ -join ' ')"
    $p = Start-Process $Exe -ArgumentList $args_ -PassThru
    $null = $p.Handle  # cache the handle so ExitCode is available after WaitForExit
    return $p
}
function Wait-Setup($Process, [int]$TimeoutMin = 75) {
    if (-not $Process.WaitForExit($TimeoutMin * 60 * 1000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw "setup did not finish within $TimeoutMin minutes"
    }
    return $Process.ExitCode
}
function Invoke-Setup([string]$Exe, [string]$Label, [string[]]$Extra = @()) { Wait-Setup (Start-Setup $Exe $Label $Extra) }
function Get-BurnLog([string]$Label) { $p = Get-EvidencePath "burn-$Label.log"; if (Test-Path $p) { Get-Content $p -Raw } else { '' } }
function Get-BurnFailureLayer([string]$Label) {
    $map = @{ WebView2Runtime = 'prerequisite'; PostgreSQLPasswordPrep = 'prerequisite'; PostgreSQLPrereq = 'prerequisite'
              PostgreSQLPasswordCleanup = 'prerequisite'; PostgreSQLVerify = 'prerequisite'; RoofSpanOfficeMsi = 'msi' }
    foreach ($m in [regex]::Matches((Get-BurnLog $Label), 'Applied execute package: (\w+), result: 0x([0-9a-fA-F]+)')) {
        if ([Convert]::ToInt64($m.Groups[2].Value, 16) -ne 0) {
            $pkg = $m.Groups[1].Value
            if ($pkg -eq 'RoofSpanUpgradeCoordinator') {
                $st = Get-CoordinatorState
                $h = if ($st) { @($st.history | ForEach-Object { $_.state }) } else { @() }
                if ($st -and $st.state -eq 'FAILED') { return 'recovery' }
                $layers = @{ PREFLIGHT = 'backup'; BACKING_UP = 'backup'; BACKUP_VERIFIED = 'backup'; SERVICES_STOPPED = 'backup'
                             INSTALLING = 'msi'; MIGRATING = 'migration'; STARTING = 'service-startup'; HEALTH_CHECKING = 'health-check' }
                $pre = if ($h -contains 'RESTORING') { $h[0..([array]::IndexOf($h, 'RESTORING') - 1)] } else { $h }
                for ($i = $pre.Count - 1; $i -ge 0; $i--) { if ($layers.ContainsKey($pre[$i])) { return $layers[$pre[$i]] } }
                return 'recovery'
            }
            if ($map.ContainsKey($pkg)) { return $map[$pkg] }
            return 'msi'
        }
    }
    if ((Get-BurnLog $Label) -notmatch 'Applying execute package') { return 'burn-detection' }
    return 'msi'
}
function Assert-SetupSucceeded([string]$Label, [int]$Code) {
    if ($Code -notin 0, 3010) { Set-Layer (Get-BurnFailureLayer $Label) }
    Assert-True "$Label setup exit 0/3010" ($Code -in 0, 3010) "exit=$Code"
}
function Assert-BurnDidNotApply([string]$Label, [string]$Package) {
    Assert-True "$Label did not run $Package" ((Get-BurnLog $Label) -notmatch "Applying execute package: $Package,") ''
}

# -- Office health ---------------------------------------------------------------------------------------------
function Wait-OfficeHealthy([string]$Version = '', [string]$BuildSha = '', [int]$TimeoutSec = 300) {
    Wait-Until { (Invoke-WebRequest "$script:Api/api/health" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } $TimeoutSec '/api/health 200' | Out-Null
    if ($BuildSha) {
        $want = "$Version/$BuildSha"
        Wait-Until { (Get-ApiVersion) -eq $want } 120 "/api/version = $want" | Out-Null
    } elseif ($Version) {
        $msi = Get-OfficeMsi
        Assert-True "installed Office MSI is $Version" ($msi -and "$($msi.DisplayVersion)" -eq $Version) "installed=$(if ($msi) { $msi.DisplayVersion } else { 'absent' })"
    }
}
function Assert-OfficeServicesRunning([string]$Label) {
    foreach ($s in $script:OfficeServices) {
        $ok = Wait-Until { (Get-Service $s -ErrorAction SilentlyContinue).Status -eq 'Running' } 180 "$s Running" -PollMs 1000
        Assert-True "$Label $s running" $ok ''
    }
}

# -- machine preparation -----------------------------------------------------------------------------------------
function Remove-RunnerPostgreSQL {
    foreach ($s in @(Get-CimInstance Win32_Service | Where-Object { $_.Name -match 'postgres' -and $_.Name -ne 'RoofSpanPostgreSQL' })) {
        Stop-Service $s.Name -Force -ErrorAction SilentlyContinue
        & sc.exe delete $s.Name | Out-Null
        Wait-Until { -not (Get-Service $s.Name -ErrorAction SilentlyContinue) } 60 "service $($s.Name) deleted" | Out-Null
        Write-Host "removed runner PostgreSQL service $($s.Name)"
    }
    if (Test-Path 'C:\Program Files\PostgreSQL') { Move-Item 'C:\Program Files\PostgreSQL' 'C:\rs-runner-postgresql-moved' -Force }
    Wait-Until { -not (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue) } 60 'port 5432 free' | Out-Null
}
function Assert-CleanMachine {
    Assert-True 'clean: no RoofSpanPostgreSQL service' (-not (Get-Service RoofSpanPostgreSQL -ErrorAction SilentlyContinue)) ''
    Assert-True 'clean: no PostgreSQL service at all' (-not (Get-Service '*postgres*' -ErrorAction SilentlyContinue)) ''
    Assert-True 'clean: no RoofSpan ProgramData' (-not (Test-Path $script:Data)) ''
    Assert-True 'clean: no Office product' (-not (Get-OfficeMsi)) ''
    Assert-True 'clean: port 5432 free' (-not (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue)) ''
}
function Get-PinnedEdb {
    $edb = Join-Path $env:RUNNER_TEMP 'fixture-postgresql-16.4-1-windows-x64.exe'
    if (-not (Test-Path $edb)) { Invoke-WebRequest $script:EdbUrl -OutFile $edb }
    Assert-True 'fixture EDB installer matches pinned SHA-256' ((Get-Sha256 $edb) -eq $script:EdbSha256) ''
    return $edb
}
function Install-EdbFixture([string]$ServiceName, [int]$Port, [string]$Prefix, [string]$DataDir, [string]$Password) {
    $edb = Get-PinnedEdb
    $opt = Join-Path $env:RUNNER_TEMP "edb-$ServiceName.optionfile"
    Set-Content -Encoding ASCII $opt @("mode=unattended", "unattendedmodeui=none", "superpassword=$Password", "serverport=$Port",
        "servicename=$ServiceName", "prefix=$Prefix", "datadir=$DataDir", "disable-components=pgAdmin,stackbuilder")
    try { $p = Start-Process $edb -ArgumentList @('--optionfile', "`"$opt`"") -Wait -PassThru } finally { Remove-Item $opt -Force -ErrorAction SilentlyContinue }
    Assert-True "fixture EDB $ServiceName installed" ($p.ExitCode -eq 0) "exit=$($p.ExitCode)"
    Wait-Until { Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue } 120 "fixture PostgreSQL listening on $Port" | Out-Null
}
function Start-PortHolder([int]$Port) {
    $code = "`$l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port); `$l.ExclusiveAddressUse = `$true; `$l.Start(); while (`$true) { `$l.AcceptTcpClient().Close() }"
    $p = Start-Process pwsh -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))) -PassThru -WindowStyle Hidden
    Wait-Until { Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $p.Id } } 30 "port holder on $Port" | Out-Null
    Add-Cleanup ([scriptblock]::Create("Stop-Process -Id $($p.Id) -Force -ErrorAction SilentlyContinue"))
    return $p
}
function Add-DenyAce([string]$Path, [string]$Rights) {
    & icacls.exe $Path /deny "*S-1-1-0:($Rights)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls deny on $Path failed" }
    Add-Cleanup ([scriptblock]::Create("& icacls.exe '$Path' /remove:d '*S-1-1-0' | Out-Null"))
}
function Remove-DenyAce([string]$Path) { & icacls.exe $Path /remove:d '*S-1-1-0' | Out-Null }
function Mount-TinyVolume([string]$MountDir, [int]$SizeMB) {
    if ((Test-Path $MountDir) -and (Get-ChildItem $MountDir -Force)) { throw "$MountDir is not empty" }
    New-Item -ItemType Directory -Force $MountDir | Out-Null
    $vhd = Join-Path $env:RUNNER_TEMP 'rs-tiny-backup.vhdx'
    $script_ = Join-Path $env:RUNNER_TEMP 'rs-tiny-mount.txt'
    Set-Content -Encoding ASCII $script_ @("create vdisk file=`"$vhd`" maximum=$SizeMB type=fixed", "select vdisk file=`"$vhd`"", 'attach vdisk',
        'create partition primary', 'format fs=ntfs quick label=RSTINY', "assign mount=`"$MountDir`"")
    & diskpart.exe /s $script_ | Out-File -Encoding UTF8 (Get-EvidencePath 'diskpart-mount.log')
    if ($LASTEXITCODE -ne 0) { throw 'diskpart could not create the tiny backup volume' }
    $detach = Join-Path $env:RUNNER_TEMP 'rs-tiny-detach.txt'
    Set-Content -Encoding ASCII $detach @("select vdisk file=`"$vhd`"", 'detach vdisk')
    Add-Cleanup ([scriptblock]::Create("& diskpart.exe /s '$detach' | Out-Null"))
    $free = [long](& python -c "import shutil,sys; print(shutil.disk_usage(sys.argv[1]).free)" $MountDir)
    Assert-True 'tiny backup volume mounted under upgrade-backups' ($free -gt 0 -and $free -lt ($SizeMB * 1MB)) "free=$free"
}
function Block-Internet {
    New-NetFirewallRule -DisplayName 'RoofSpanMatrixOffline' -Direction Outbound -Action Block -RemoteAddress Internet -Profile Any | Out-Null
    Add-Cleanup { Remove-NetFirewallRule -DisplayName 'RoofSpanMatrixOffline' -ErrorAction SilentlyContinue }
    foreach ($target in @(@('1.1.1.1', 443), @('8.8.8.8', 53), @('13.107.4.52', 80))) {
        $c = [System.Net.Sockets.TcpClient]::new()
        try { $connected = $c.ConnectAsync($target[0], $target[1]).Wait(5000) -and $c.Connected } catch { $connected = $false } finally { $c.Dispose() }
        Assert-True "outbound $($target[0]):$($target[1]) is blocked" (-not $connected) ''
    }
}
function Unblock-Internet { Remove-NetFirewallRule -DisplayName 'RoofSpanMatrixOffline' -ErrorAction SilentlyContinue }

# -- upgrade baselines + coordinator observation -------------------------------------------------------------------
function Install-Baseline([string]$Which) {
    $W = $Which.ToUpperInvariant()
    $url = [Environment]::GetEnvironmentVariable("ROOFSPAN_BASELINE_${W}_URL")
    $sha = "$([Environment]::GetEnvironmentVariable("ROOFSPAN_BASELINE_${W}_SHA256"))".ToLowerInvariant()
    $ver = [Environment]::GetEnvironmentVariable("ROOFSPAN_BASELINE_${W}_VERSION")
    if (-not $url -or -not $sha -or -not $ver) { throw "BLOCKED_MISSING_BASELINE: ROOFSPAN_BASELINE_${W}_URL/_SHA256/_VERSION are not configured" }
    $exe = Join-Path $env:RUNNER_TEMP "baseline-$Which\RoofSpanSetup.exe"
    New-Item -ItemType Directory -Force (Split-Path $exe) | Out-Null
    Invoke-WebRequest $url -OutFile $exe
    Assert-True "baseline $W matches its pinned SHA-256" ((Get-Sha256 $exe) -eq $sha) "pinned=$sha"
    $code = Invoke-Setup $exe "install-baseline-$Which"
    Assert-SetupSucceeded "install-baseline-$Which" $code
    Wait-OfficeHealthy -Version $ver
    return $ver
}
function Wait-CoordinatorState([string[]]$States, [int]$TimeoutSec, $Process = $null) {
    return Wait-Until {
        $st = Get-CoordinatorState
        if ($st -and $st.state -in $States) { return $st }
        if ($Process -and $Process.HasExited) { throw "ABORT: setup exited (code $($Process.ExitCode)) before the coordinator reached $($States -join ',')" }
        return $null
    } $TimeoutSec ("coordinator state in " + ($States -join ',')) -PollMs 250
}
function Get-StateHistory($St) { if ($St) { @($St.history | ForEach-Object { $_.state }) } else { @() } }
function Test-MsiBusy { try { [System.Threading.Mutex]::OpenExisting('Global\_MSIExecute').Dispose(); return $true } catch { return $false } }

# -- diagnostics ---------------------------------------------------------------------------------------------------
function Save-Diagnostics {
    $d = $script:Evidence
    $logs = Join-Path $d 'programdata-logs'; New-Item -ItemType Directory -Force $logs | Out-Null
    Get-ChildItem (Join-Path $script:Data 'logs') -Filter *.log -ErrorAction SilentlyContinue | Copy-Item -Destination $logs -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $script:Data 'prereq-diag.log') $d -ErrorAction SilentlyContinue
    if (Test-Path $script:StateFile) { Copy-Item $script:StateFile (Join-Path $d 'state-final.json') -ErrorAction SilentlyContinue }
    Copy-Item (Join-Path $script:Data 'upgrade\journal.log') (Join-Path $d 'upgrade-journal.log') -ErrorAction SilentlyContinue
    Get-ChildItem (Join-Path $script:Data 'upgrade-backups') -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $a = $_.Name
        Get-ChildItem $_.FullName -File -Include *.log, manifest.json -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $d "backup-$a-$($_.Name)") -ErrorAction SilentlyContinue }
    }
    Get-ChildItem $env:TEMP -Filter '*.log' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $script:Started } |
        Where-Object { (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue) -match 'RoofSpan' } |
        ForEach-Object { Copy-Item $_.FullName (Join-Path $d "temp-$($_.Name)") -ErrorAction SilentlyContinue }
    try {
        Get-WinEvent -FilterHashtable @{ LogName = 'Application', 'System'; StartTime = $script:Started } -ErrorAction SilentlyContinue |
            Where-Object { $_.ProviderName -match 'MsiInstaller|Service Control Manager|RoofSpan|PostgreSQL|Application Error|Windows Error Reporting|RestartManager' } |
            ForEach-Object { "{0:o} [{1}] {2} {3}: {4}" -f $_.TimeCreated, $_.LevelDisplayName, $_.ProviderName, $_.Id, ($_.Message -replace '\s+', ' ') } |
            Set-Content -Encoding UTF8 (Join-Path $d 'eventlog.txt')
    } catch { Write-Warning 'event log extract failed' }
    $versions = [ordered]@{}
    foreach ($s in 'roofspan-backend', 'roofspan-relay-connector', 'roofspan-update-service') { $versions[$s] = Get-BuildInfo $s }
    $msi = Get-OfficeMsi; $bundle = Get-OfficeBundle
    $versions['office_msi'] = if ($msi) { "$($msi.DisplayVersion)" } else { 'absent' }
    $versions['bundle'] = if ($bundle) { "$($bundle.DisplayVersion)" } else { 'absent' }
    $versions['api'] = Get-ApiVersion
    $versions | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $d 'versions.json')
    Get-CimInstance Win32_Service | Where-Object { $_.Name -like 'RoofSpan*' -or $_.Name -like '*postgres*' } |
        Select-Object Name, State, StartMode, StartName, PathName | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $d 'services.json')
}

Export-ModuleMember -Function * -Variable Data, InstallRoot, Cfg, IdentityDir, StateFile, OfficeServices
