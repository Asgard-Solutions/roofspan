# Download a SHA-256-pinned, Authenticode-verified EnterpriseDB PostgreSQL installer for CI.
# Default matches the historical CI baseline. To test the installer used on local
# release builds, set BOTH repository variables ROOFSPAN_CI_EDB_URL and
# ROOFSPAN_CI_EDB_SHA256. Partial overrides fail closed.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'

$defaultUrl = 'https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe'
$defaultSha = 'f4bf0ac4b33471f18aad7d1d9cc52613003f3a3a612aae167366bf7f7840b2bc'
$customUrl = "$env:ROOFSPAN_CI_EDB_URL".Trim()
$customSha = "$env:ROOFSPAN_CI_EDB_SHA256".Trim()
if ([bool]$customUrl -ne [bool]$customSha) {
    throw 'Configure BOTH ROOFSPAN_CI_EDB_URL and ROOFSPAN_CI_EDB_SHA256, or neither.'
}
$url = if ($customUrl) { $customUrl } else { $defaultUrl }
$sha = if ($customSha) { $customSha.ToLowerInvariant() } else { $defaultSha }
if ($sha -notmatch '^[0-9a-f]{64}$') { throw 'EDB SHA-256 must contain exactly 64 hexadecimal characters.' }
$uri = [uri]$url
if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'get.enterprisedb.com' -or
    $uri.AbsolutePath -notmatch '^/postgresql/postgresql-16\.\d+-\d+-windows-x64\.exe$' -or
    $uri.Query -or $uri.Fragment) {
    throw 'EDB URL must be a versioned HTTPS Windows x64 installer hosted at get.enterprisedb.com.'
}
$parent = Split-Path -Parent $Destination
New-Item -ItemType Directory -Force -Path $parent | Out-Null
Write-Host "Downloading SHA-256-pinned PostgreSQL prerequisite: $($uri.Segments[-1])"
Invoke-WebRequest -Uri $url -OutFile $Destination -MaximumRetryCount 3 -RetryIntervalSec 5
if ((Get-Item -LiteralPath $Destination).Length -lt 100MB) {
    throw 'EDB prerequisite is unexpectedly small; refusing to use a bootstrapper/invalid file.'
}
$actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $sha) { throw "EDB installer SHA-256 $actual does not match pinned $sha" }
$sig = Get-AuthenticodeSignature -FilePath $Destination
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'EnterpriseDB') {
    throw "EDB installer signature invalid or unexpected publisher (status $($sig.Status))."
}
Write-Host "PASS: EDB prerequisite verified ($actual, $($sig.SignerCertificate.Subject))"
