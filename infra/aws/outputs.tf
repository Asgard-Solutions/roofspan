output "control_plane_url" {
  value       = "https://${var.cp_hostname}"
  description = "CONTROL_PLANE_BASE_URL for RoofSpan Office + Mobile."
}
output "relay_wss_url" {
  value       = "wss://${var.relay_hostname}"
  description = "RELAY_WSS_URL for RoofSpan Office + Mobile (independent of the CP URL)."
}
output "alb_dns_name" {
  value = aws_lb.main.dns_name
}
output "ecr_control_plane_repo" {
  value = aws_ecr_repository.control_plane.repository_url
}
output "ecr_relay_repo" {
  value = aws_ecr_repository.relay.repository_url
}
output "entitlement_signing_kms_key_id" {
  value = aws_kms_key.entitlement_signing.key_id
}
output "cp_rds_endpoint" {
  value = aws_db_instance.control_plane.address
}
output "valkey_primary_endpoint" {
  value = aws_elasticache_replication_group.valkey.primary_endpoint_address
}
output "operator_user_pool_id" {
  value = aws_cognito_user_pool.operators.id
}
output "app_secret_arns" {
  value = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
}
