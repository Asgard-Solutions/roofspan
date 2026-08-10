resource "aws_cloudwatch_log_group" "cp" {
  name              = "/roofspan/${var.environment}/control-plane"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.general.arn
}
resource "aws_cloudwatch_log_group" "relay" {
  name              = "/roofspan/${var.environment}/relay"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.general.arn
}

locals {
  alarm_actions = var.alarm_sns_topic_arn == "" ? [] : [var.alarm_sns_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "cp_unhealthy_hosts" {
  alarm_name          = "${local.name}-cp-unhealthy-hosts"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { TargetGroup = aws_lb_target_group.cp.arn_suffix, LoadBalancer = aws_lb.main.arn_suffix }
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "relay_unhealthy_hosts" {
  alarm_name          = "${local.name}-relay-unhealthy-hosts"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { TargetGroup = aws_lb_target_group.relay.arn_suffix, LoadBalancer = aws_lb.main.arn_suffix }
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 25
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-rds-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.control_plane.identifier }
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${local.name}-rds-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 2147483648 # 2 GiB
  comparison_operator = "LessThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.control_plane.identifier }
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "valkey_memory" {
  alarm_name          = "${local.name}-valkey-memory"
  namespace           = "AWS/ElastiCache"
  metric_name         = "DatabaseMemoryUsagePercentage"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { ReplicationGroupId = aws_elasticache_replication_group.valkey.replication_group_id }
  alarm_actions       = local.alarm_actions
}
