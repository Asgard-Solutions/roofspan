# RoofSpan INTERNAL operator auth (not customer SSO). Cognito user pool for CP admin endpoints.
resource "aws_cognito_user_pool" "operators" {
  name                     = "${local.name}-operators"
  mfa_configuration        = "OPTIONAL"
  auto_verified_attributes = ["email"]
  admin_create_user_config {
    allow_admin_create_user_only = true # operators are provisioned by RoofSpan, no self-signup
  }
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  software_token_mfa_configuration {
    enabled = true
  }
  tags = { Name = "${local.name}-operators" }
}

resource "aws_cognito_user_pool_client" "cp_admin" {
  name                          = "${local.name}-cp-admin"
  user_pool_id                  = aws_cognito_user_pool.operators.id
  generate_secret               = true
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  access_token_validity         = 60
  id_token_validity             = 60
  refresh_token_validity        = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
