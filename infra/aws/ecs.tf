resource "aws_ecs_cluster" "main" {
  name = "${local.name}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# CP secret injections (RDS master secret is JSON; app reads username/password/host from it).
locals {
  cp_secrets = [
    { name = "STRIPE_SECRET_KEY", valueFrom = aws_secretsmanager_secret.app["stripe_secret_key"].arn },
    { name = "STRIPE_WEBHOOK_SECRET", valueFrom = aws_secretsmanager_secret.app["stripe_webhook_secret"].arn },
    { name = "RDS_MASTER_SECRET", valueFrom = aws_db_instance.control_plane.master_user_secret[0].secret_arn },
  ]
  cp_env = [
    { name = "CP_ENV", value = "production" },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "BILLING_MODE", value = "stripe" },
    { name = "ENTITLEMENT_SIGNER", value = "kms" },
    { name = "CP_KMS_SIGNING_KEY_ID", value = aws_kms_key.entitlement_signing.key_id },
    { name = "CP_OPERATOR_ISSUER", value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.operators.id}" },
    { name = "CP_OPERATOR_AUDIENCE", value = aws_cognito_user_pool_client.cp_admin.id },
    { name = "APP_BASE_URL", value = "https://${var.domain}" },
    { name = "RDS_HOST", value = aws_db_instance.control_plane.address },
    { name = "RDS_DB", value = aws_db_instance.control_plane.db_name },
  ]
  relay_env = [
    { name = "RELAY_ENV", value = "production" },
    { name = "RELAY_REGISTRY", value = "valkey" },
    { name = "RELAY_VALKEY_URL", value = "rediss://${aws_elasticache_replication_group.valkey.primary_endpoint_address}:6379" },
    # RELAY_NODE_ID is intentionally NOT a static env var (it would be identical across all tasks).
    # Each relay task derives a UNIQUE node id at runtime from the ECS Task Metadata endpoint
    # (ECS_CONTAINER_METADATA_URI_V4 -> TaskARN, injected automatically on Fargate platform >= 1.4.0);
    # see backend/relay/config.py::_resolve_node_id. Startup fails fast if a unique id can't be established.
  ]
}

resource "aws_ecs_task_definition" "cp" {
  family                   = "${local.name}-cp"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cp_cpu
  memory                   = var.cp_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.cp_task.arn
  container_definitions = jsonencode([{
    name         = "control-plane"
    image        = var.control_plane_image
    essential    = true
    portMappings = [{ containerPort = var.cp_container_port, protocol = "tcp" }]
    environment  = local.cp_env
    secrets      = local.cp_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.cp.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "cp"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${var.cp_container_port}/api/control-plane/health').status==200 else 1)\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_ecs_task_definition" "relay" {
  family                   = "${local.name}-relay"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.relay_cpu
  memory                   = var.relay_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.relay_task.arn
  container_definitions = jsonencode([{
    name         = "relay"
    image        = var.relay_image
    essential    = true
    portMappings = [{ containerPort = var.relay_container_port, protocol = "tcp" }]
    environment  = local.relay_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.relay.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "relay"
      }
    }
  }])
}

resource "aws_ecs_service" "cp" {
  name            = "${local.name}-cp"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.cp.arn
  desired_count   = var.cp_desired_count
  launch_type     = "FARGATE"
  # Only ONE task runs migrations (advisory lock in the entrypoint); rolling deploy keeps 1 healthy.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.cp.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.cp.arn
    container_name   = "control-plane"
    container_port   = var.cp_container_port
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "relay" {
  name            = "${local.name}-relay"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.relay.arn
  desired_count   = var.relay_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.relay.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.relay.arn
    container_name   = "relay"
    container_port   = var.relay_container_port
  }
  depends_on = [aws_lb_listener.https]
}

# ---- Conservative autoscaling (CPU target) ----
resource "aws_appautoscaling_target" "cp" {
  max_capacity       = var.cp_max_count
  min_capacity       = var.cp_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.cp.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}
resource "aws_appautoscaling_policy" "cp_cpu" {
  name               = "${local.name}-cp-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.cp.resource_id
  scalable_dimension = aws_appautoscaling_target.cp.scalable_dimension
  service_namespace  = aws_appautoscaling_target.cp.service_namespace
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 60
  }
}

resource "aws_appautoscaling_target" "relay" {
  max_capacity       = var.relay_max_count
  min_capacity       = var.relay_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.relay.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}
resource "aws_appautoscaling_policy" "relay_cpu" {
  name               = "${local.name}-relay-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.relay.resource_id
  scalable_dimension = aws_appautoscaling_target.relay.scalable_dimension
  service_namespace  = aws_appautoscaling_target.relay.service_namespace
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 60
  }
}
