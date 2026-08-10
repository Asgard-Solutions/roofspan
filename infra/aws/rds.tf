resource "aws_db_subnet_group" "cp" {
  name       = "${local.name}-cp-db-subnets"
  subnet_ids = aws_subnet.data[*].id
  tags       = { Name = "${local.name}-cp-db-subnets" }
}

resource "aws_db_instance" "control_plane" {
  identifier     = "${local.name}-cp"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.general.arn

  db_name  = "roofspan_control_plane"
  username = "roofspan_cp"
  # No plaintext password in TF: RDS creates + manages the master secret in Secrets Manager.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.general.arn

  db_subnet_group_name   = aws_db_subnet_group.cp.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = var.rds_multi_az

  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "05:00-06:00"
  deletion_protection     = var.environment == "production"
  skip_final_snapshot     = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${local.name}-cp-final" : null

  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
  apply_immediately            = false

  tags = { Name = "${local.name}-cp-rds", DataClass = "commercial-metadata-only" }
}
