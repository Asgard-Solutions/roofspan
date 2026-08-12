# RoofSpan AWS deploy-prep — ONE-TIME Terraform remote-state bootstrap (Windows/PowerShell).
# Creates the S3 state bucket via AWS CLI (no Terraform). S3-native locking (no DynamoDB). Idempotent.
$ErrorActionPreference = "Stop"

$ExpectedAccount = if ($env:EXPECTED_ACCOUNT_ID) { $env:EXPECTED_ACCOUNT_ID } else { "391722048303" }
$Region = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-2" }
$Bucket = if ($env:TF_STATE_BUCKET) { $env:TF_STATE_BUCKET } else { "roofspan-tfstate-$ExpectedAccount-$Region" }
$StateKmsKeyId = $env:STATE_KMS_KEY_ID

Write-Host "Bucket=$Bucket Region=$Region Locking=S3-native(no DynamoDB)"

$AccountId = (aws sts get-caller-identity --query Account --output text).Trim()
if ($AccountId -ne $ExpectedAccount) { throw "account $AccountId != expected $ExpectedAccount." }

$confirm = Read-Host "Type EXACTLY 'bootstrap-state' to CREATE the state bucket in $AccountId/$Region"
if ($confirm -ne "bootstrap-state") { throw "Aborted." }

aws s3api head-bucket --bucket $Bucket 2>$null
if ($LASTEXITCODE -ne 0) {
  if ($Region -eq "us-east-1") {
    aws s3api create-bucket --bucket $Bucket --region $Region
  } else {
    aws s3api create-bucket --bucket $Bucket --region $Region --create-bucket-configuration "LocationConstraint=$Region"
  }
  Write-Host "Bucket created."
} else { Write-Host "Bucket already exists — skipping create." }

aws s3api put-bucket-versioning --bucket $Bucket --versioning-configuration Status=Enabled

if ($StateKmsKeyId) {
  $enc = "{`"Rules`":[{`"ApplyServerSideEncryptionByDefault`":{`"SSEAlgorithm`":`"aws:kms`",`"KMSMasterKeyID`":`"$StateKmsKeyId`"},`"BucketKeyEnabled`":true}]}"
} else {
  $enc = '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'
}
aws s3api put-bucket-encryption --bucket $Bucket --server-side-encryption-configuration $enc

aws s3api put-public-access-block --bucket $Bucket --public-access-block-configuration `
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

Write-Host ""
Write-Host "State bucket ready. Then:"
Write-Host "  `$env:TF_STATE_BUCKET='$Bucket'"
Write-Host "  infra/aws/scripts/bootstrap-ecr.ps1  (or .sh)"
