# General-purpose symmetric CMK (log/ECR/secrets encryption).
resource "aws_kms_key" "general" {
  description             = "${local.name} general encryption (logs, ECR, secrets)"
  deletion_window_in_days = 14
  enable_key_rotation     = true
  tags                    = { Name = "${local.name}-kms-general" }
}
resource "aws_kms_alias" "general" {
  name          = "alias/${local.name}-general"
  target_key_id = aws_kms_key.general.id
}

# Dedicated ASYMMETRIC Ed25519 signing key for RoofSpan ENTITLEMENT issuance. Private key NEVER leaves
# KMS. Separate trust domain from Windows-update signing / installation identity / Mobile credentials.
resource "aws_kms_key" "entitlement_signing" {
  description              = "${local.name} entitlement signing (Ed25519, sign/verify)"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_EDWARDS25519"
  deletion_window_in_days  = 30
  tags                     = { Name = "${local.name}-entitlement-signing", TrustDomain = "roofspan-entitlement" }
}
resource "aws_kms_alias" "entitlement_signing" {
  name          = "alias/${local.name}-entitlement-signing"
  target_key_id = aws_kms_key.entitlement_signing.id
}
