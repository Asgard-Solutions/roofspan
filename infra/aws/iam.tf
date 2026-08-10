data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: pull images, write logs, read secrets for injection.
resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
data "aws_iam_policy_document" "execution_extra" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = concat([for s in aws_secretsmanager_secret.app : s.arn], [aws_db_instance.control_plane.master_user_secret[0].secret_arn])
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.general.arn]
  }
}
resource "aws_iam_role_policy" "execution_extra" {
  name   = "${local.name}-execution-extra"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_extra.json
}

# CP task role: sign entitlements with the dedicated KMS Ed25519 key + read its own secrets.
resource "aws_iam_role" "cp_task" {
  name               = "${local.name}-cp-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
data "aws_iam_policy_document" "cp_task" {
  statement {
    sid       = "EntitlementSign"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.entitlement_signing.arn]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = concat([for s in aws_secretsmanager_secret.app : s.arn], [aws_db_instance.control_plane.master_user_secret[0].secret_arn])
  }
}
resource "aws_iam_role_policy" "cp_task" {
  name   = "${local.name}-cp-task"
  role   = aws_iam_role.cp_task.id
  policy = data.aws_iam_policy_document.cp_task.json
}

# Relay task role: minimal (network to Valkey is via SG; no signing, no DB).
resource "aws_iam_role" "relay_task" {
  name               = "${local.name}-relay-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
