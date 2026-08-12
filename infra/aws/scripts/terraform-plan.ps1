# RoofSpan AWS deploy-prep — safe local Terraform PLAN runner (Windows/PowerShell). NEVER applies.
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackDir  = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $StackDir

$Tfvars = if ($env:TFVARS) { $env:TFVARS } else { "terraform.tfvars" }
if (-not (Test-Path $Tfvars)) { throw "$Tfvars not found. Copy terraform.tfvars.example and fill it in." }

$Region = if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { $null }
if (-not $Region) { throw "AWS_REGION not set." }
$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
$ExpectedAccount = if ($env:EXPECTED_ACCOUNT_ID) { $env:EXPECTED_ACCOUNT_ID } else { "391722048303" }
if ($AccountId -ne $ExpectedAccount) { throw "account $AccountId != expected $ExpectedAccount." }

function Get-Tfvar($name) {
  $line = Select-String -Path $Tfvars -Pattern "^\s*$name\s*=" | Select-Object -First 1
  if (-not $line) { return "" }
  ($line.Line -split "=", 2)[1].Trim().Trim('"')
}
$TfRegion = Get-Tfvar "aws_region"
$TfDns    = Get-Tfvar "dns_provider"; if (-not $TfDns) { $TfDns = "external" }
$TfZone   = Get-Tfvar "route53_zone_id"
$TfEnv    = Get-Tfvar "environment"
$TfCp     = Get-Tfvar "control_plane_image"
$TfRelay  = Get-Tfvar "relay_image"

Write-Host "AWS account (live)  : $AccountId"
Write-Host "AWS region (shell)  : $Region"
Write-Host "tfvars aws_region   : $TfRegion"
Write-Host "tfvars dns_provider : $TfDns"
Write-Host "tfvars route53_zone : $TfZone"
Write-Host "tfvars environment  : $TfEnv"
Write-Host "control_plane_image : $TfCp"
Write-Host "relay_image         : $TfRelay"

if (-not $TfRegion) { throw "aws_region not set in $Tfvars." }
if ($TfRegion -ne $Region) { throw "shell AWS_REGION ($Region) != tfvars aws_region ($TfRegion)." }
if ($TfDns -eq "route53") {
  if (-not $TfZone -or $TfZone -match "^(REQUIRED|Z_PENDING|CHANGE)") {
    throw "dns_provider=route53 but route53_zone_id is not a real hosted-zone id."
  }
} else {
  Write-Host "DNS mode = external (GoDaddy): route53_zone_id not required; Terraform creates NO DNS records."
  Write-Host "After apply: terraform output acm_validation_records; terraform output external_dns_endpoint_records"
}
if (("$TfCp$TfRelay" -match "REPLACE") -or (-not $TfCp) -or (-not $TfRelay)) {
  throw "image references still placeholders. Run build-push-images first."
}

$confirm = Read-Host "Type EXACTLY 'plan' to run fmt/init/validate/plan (NO apply)"
if ($confirm -ne "plan") { throw "Aborted." }

if ($env:TF_STATE_BUCKET) {
  $Key = if ($env:TF_STATE_KEY) { $env:TF_STATE_KEY } else { "control-plane-relay/terraform.tfstate" }
  terraform init -reconfigure `
    -backend-config="bucket=$($env:TF_STATE_BUCKET)" `
    -backend-config="key=$Key" `
    -backend-config="region=$Region" `
    -backend-config="use_lockfile=true" `
    -backend-config="encrypt=true"
} elseif ($env:PLAN_LOCAL_STATE -eq "1") {
  terraform init -reconfigure
} else {
  throw "Remote state not configured. Set TF_STATE_BUCKET (see REMOTE_STATE.md) or PLAN_LOCAL_STATE=1 for preview."
}

terraform fmt -check -recursive
terraform validate
terraform plan -input=false -var-file="$Tfvars" -out=tfplan
terraform show -no-color tfplan > tfplan.txt
Write-Host "PLAN COMPLETE. Review tfplan.txt. NOTHING applied."
