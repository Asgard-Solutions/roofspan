# RoofSpan AWS deploy-prep — verify local tooling (Windows/PowerShell). Read-only.
$ErrorActionPreference = "Stop"
Write-Host "== RoofSpan deploy-prep: tooling check =="
$fail = $false

function Need($bin, $hint) {
  $cmd = Get-Command $bin -ErrorAction SilentlyContinue
  if ($cmd) {
    $ver = (& $bin --version 2>&1 | Select-Object -First 1)
    Write-Host ("  OK  {0,-10} {1}" -f $bin, $ver)
  } else {
    Write-Host ("  MISSING {0,-8} -> {1}" -f $bin, $hint)
    $script:fail = $true
  }
}

Need "aws"       "Install AWS CLI v2."
Need "docker"    "Install Docker Desktop and start it."
Need "terraform" "Install Terraform >= 1.10."
Need "git"       "Install Git."

if (Get-Command aws -ErrorAction SilentlyContinue) {
  if (-not ((aws --version 2>&1) -match "aws-cli/2")) { Write-Host "  WARN aws-cli is not v2."; $fail = $true }
}
if (Get-Command docker -ErrorAction SilentlyContinue) {
  docker info *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  OK  docker daemon reachable" } else { Write-Host "  WARN docker daemon not reachable."; $fail = $true }
  docker buildx version *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  OK  docker buildx present" } else { Write-Host "  WARN docker buildx missing (needed for --platform)." }
}

Write-Host ""
if ($fail) { Write-Host "RESULT: prerequisites INCOMPLETE."; exit 1 }
Write-Host "RESULT: all prerequisites present."
