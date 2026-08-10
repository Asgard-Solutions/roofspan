# VPC endpoints reduce NAT dependence + keep AWS-API traffic private (ECR pulls, logs, secrets, KMS).
resource "aws_security_group" "endpoints" {
  name        = "${local.name}-vpce-sg"
  description = "Allow HTTPS from app subnets to interface endpoints"
  vpc_id      = aws_vpc.main.id
  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-vpce-sg" }
}

# Gateway endpoints (free): S3 (ECR layers, general), DynamoDB (optional for TF state locking use elsewhere).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(aws_route_table.private[*].id, [aws_route_table.data.id])
  tags              = { Name = "${local.name}-vpce-s3" }
}

locals {
  interface_endpoints = [
    "ecr.api", "ecr.dkr", "logs", "secretsmanager", "kms", "sts", "elasticache",
  ]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(local.interface_endpoints)
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.app[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = { Name = "${local.name}-vpce-${each.value}" }
}
