# RoofSpan AWS deploy-prep — Stage A ECR bootstrap (Windows/PowerShell).
# Applies ONLY the ECR repos + their KMS key (narrow -target). Requires typed confirmation + remote state.
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackDir  = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $StackDir

$Region = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-2" }
$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
$ExpectedAccount = if ($env:EXPECTED_ACCOUNT_ID) { $env:EXPECTED_ACCOUNT_ID } else { "391722048303" }
if ($AccountId -ne $ExpectedAccount) { throw "account $AccountId != expected $ExpectedAccount." }
if (-not $env:TF_STATE_BUCKET) { throw "TF_STATE_BUCKET not set. Run bootstrap-remote-state first (REMOTE_STATE.md)." }
$Key = if ($env:TF_STATE_KEY) { $env:TF_STATE_KEY } else { "control-plane-relay/terraform.tfstate" }

Write-Host "Stage A ECR bootstrap: account=$AccountId region=$Region state=s3://$($env:TF_STATE_BUCKET)/$Key"
$confirm = Read-Host "Type EXACTLY 'apply-ecr' to create ONLY ECR repos + KMS general key"
if ($confirm -ne "apply-ecr") { throw "Aborted." }

terraform init -reconfigure `
  -backend-config="bucket=$($env:TF_STATE_BUCKET)" `
  -backend-config="key=$Key" `
  -backend-config="region=$Region" `
  -backend-config="use_lockfile=true" `
  -backend-config="encrypt=true"

terraform apply `
  -target=aws_kms_key.general `
  -target=aws_ecr_repository.control_plane `
  -target=aws_ecr_repository.relay `
  -target=aws_ecr_lifecycle_policy.cp `
  -target=aws_ecr_lifecycle_policy.relay

Write-Host "Stage A complete. Next: build-push-images.ps1"
