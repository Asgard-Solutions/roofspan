# RoofSpan AWS deploy-prep — build, tag, push CP + Relay images to ECR (Windows/PowerShell).
# Builds linux/amd64 to match the ECS runtime_platform. Does NOT create ECR repos (Terraform owns them).
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$Platform  = "linux/amd64"
$ExpectedAccount = if ($env:EXPECTED_ACCOUNT_ID) { $env:EXPECTED_ACCOUNT_ID } else { "391722048303" }

$Region = if ($env:AWS_REGION) { $env:AWS_REGION } elseif ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { $null }
if (-not $Region) { throw "AWS_REGION not set. e.g. `$env:AWS_REGION='us-east-2'" }

$Tag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else {
  try { (git -C $RepoRoot rev-parse --short HEAD).Trim() } catch { Get-Date -Format "yyyyMMddHHmmss" }
}

$CpDockerfile    = Join-Path $RepoRoot "infra\docker\control-plane\Dockerfile"
$RelayDockerfile = Join-Path $RepoRoot "infra\docker\relay\Dockerfile"
foreach ($f in @($CpDockerfile, $RelayDockerfile, (Join-Path $RepoRoot "backend\requirements.txt"))) {
  if (-not (Test-Path $f)) { throw "Expected file missing: $f" }
}

$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
if ($AccountId -ne $ExpectedAccount) { throw "account $AccountId != expected $ExpectedAccount. Refusing to push." }
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
Write-Host "Account=$AccountId Region=$Region Registry=$Registry Tag=$Tag Platform=$Platform"

foreach ($repo in @("roofspan-control-plane", "roofspan-relay")) {
  aws ecr describe-repositories --repository-names $repo --region $Region *> $null
  if ($LASTEXITCODE -ne 0) { throw "ECR repo '$repo' missing in $Region. Run bootstrap-ecr (Stage A) first." }
}

aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $Registry

function Build-Push($name, $dockerfile) {
  $ref = "$Registry/${name}:$Tag"
  docker buildx build --platform $Platform --load -f $dockerfile -t $ref $RepoRoot
  docker push $ref
  $digest = (aws ecr describe-images --repository-name $name --region $Region --image-ids imageTag=$Tag --query "imageDetails[0].imageDigest" --output text).Trim()
  return "$Registry/$name@$digest"
}

$CpRef    = Build-Push "roofspan-control-plane" $CpDockerfile
$RelayRef = Build-Push "roofspan-relay" $RelayDockerfile

Write-Host ""
Write-Host "Paste into infra/aws/terraform.tfvars:"
Write-Host "control_plane_image = `"$CpRef`""
Write-Host "relay_image         = `"$RelayRef`""
