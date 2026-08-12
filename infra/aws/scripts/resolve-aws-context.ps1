# RoofSpan AWS deploy-prep — verify WHO and WHERE (Windows/PowerShell). Read-only. No resources changed.
$ErrorActionPreference = "Stop"

$ExpectedAccount = if ($env:EXPECTED_ACCOUNT_ID) { $env:EXPECTED_ACCOUNT_ID } else { "391722048303" }

Write-Host "== RoofSpan deploy-prep: AWS context =="
if ($env:AWS_PROFILE) { Write-Host "  Using AWS_PROFILE=$($env:AWS_PROFILE)" } else { Write-Host "  AWS_PROFILE not set — using ambient session." }

$ident = aws sts get-caller-identity --output json | ConvertFrom-Json
if (-not $ident) { throw "not authenticated. Run 'aws sso login' or configure a profile." }
Write-Host "  Identity ARN : $($ident.Arn)"
Write-Host "  Account ID   : $($ident.Account)"
if ($ident.Account -ne $ExpectedAccount) { throw "account $($ident.Account) != expected RoofSpan account $ExpectedAccount." }
Write-Host "  Account MATCHES expected RoofSpan account."

$region = if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { (aws configure get region) }
if (-not $region) { throw "no region. Set `$env:AWS_REGION='us-east-2'." }
Write-Host "  Region       : $region   <-- must be us-east-2 (app stack). NOT us-east-1 (that's only CloudFront/downloads)."

Write-Host ""
Write-Host "== Route53 (read-only) roofspan.io lookup (expected: none — DNS is at GoDaddy) =="
$zones = aws route53 list-hosted-zones-by-name --dns-name roofspan.io. --max-items 5 --output json 2>$null | ConvertFrom-Json
if ($zones -and ($zones.HostedZones | Where-Object { $_.Name -eq "roofspan.io." })) {
  $zones.HostedZones | ForEach-Object { Write-Host "    $($_.Id)  $($_.Name)" }
  Write-Host "  (Only relevant if you switch dns_provider to 'route53'.)"
} else {
  Write-Host "  No Route53 hosted zone for roofspan.io (expected — dns_provider = external / GoDaddy)."
}
Write-Host "  This script created/modified nothing."
