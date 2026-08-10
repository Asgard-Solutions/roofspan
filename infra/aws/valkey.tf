resource "aws_elasticache_subnet_group" "valkey" {
  name       = "${local.name}-valkey-subnets"
  subnet_ids = aws_subnet.data[*].id
}

# Valkey = Relay node registry + bounded Pub/Sub for cross-node frame routing. Ephemeral/reconstructable
# state only — NEVER customer business data, never a durable database.
resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id = "${local.name}-valkey"
  description          = "RoofSpan Relay registry + pub/sub (Valkey)"
  engine               = "valkey"
  engine_version       = "7.2"
  node_type            = var.valkey_node_type
  port                 = 6379

  num_node_groups         = 1
  replicas_per_node_group = var.valkey_replicas

  automatic_failover_enabled = var.valkey_replicas >= 1
  multi_az_enabled           = var.valkey_replicas >= 1

  subnet_group_name  = aws_elasticache_subnet_group.valkey.name
  security_group_ids = [aws_security_group.valkey.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = aws_kms_key.general.arn

  tags = { Name = "${local.name}-valkey", DataClass = "ephemeral-routing-only" }
}
