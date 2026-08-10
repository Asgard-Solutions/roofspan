# Empty secret CONTAINERS only — Terraform holds NO secret values. Populate out-of-band (RUNBOOK.md).
# RDS master creds are managed by RDS (manage_master_user_password) into its own Secrets Manager secret.
locals {
  app_secrets = {
    stripe_secret_key     = "Stripe production secret key (sk_live_...)"
    stripe_webhook_secret = "Stripe webhook signing secret (whsec_...)"
    revenuecat_secret     = "RevenueCat production secret (if used)"
    operator_config       = "Operator/admin auth config JSON (e.g. Cognito app secret if needed)"
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each    = local.app_secrets
  name        = "${local.name}/${each.key}"
  description = each.value
  kms_key_id  = aws_kms_key.general.arn
  tags        = { Name = "${local.name}-${each.key}" }
}
# NOTE: intentionally NO aws_secretsmanager_secret_version here — values are populated by a human/CI
# after apply so secret material never enters Terraform state or Git.
