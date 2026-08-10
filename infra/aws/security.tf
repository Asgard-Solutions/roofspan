resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "Public HTTPS to ALB only"
  vpc_id      = aws_vpc.main.id
  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTP (redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-alb-sg" }
}

resource "aws_security_group" "cp" {
  name        = "${local.name}-cp-sg"
  description = "Control Plane ECS tasks"
  vpc_id      = aws_vpc.main.id
  ingress {
    description     = "ALB -> CP"
    from_port       = var.cp_container_port
    to_port         = var.cp_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-cp-sg" }
}

resource "aws_security_group" "relay" {
  name        = "${local.name}-relay-sg"
  description = "Relay ECS tasks"
  vpc_id      = aws_vpc.main.id
  ingress {
    description     = "ALB -> Relay"
    from_port       = var.relay_container_port
    to_port         = var.relay_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-relay-sg" }
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds-sg"
  description = "RDS PostgreSQL — CP tasks only, no public access"
  vpc_id      = aws_vpc.main.id
  ingress {
    description     = "CP ECS -> Postgres"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.cp.id]
  }
  tags = { Name = "${local.name}-rds-sg" }
}

resource "aws_security_group" "valkey" {
  name        = "${local.name}-valkey-sg"
  description = "ElastiCache Valkey — Relay tasks only, no public access"
  vpc_id      = aws_vpc.main.id
  ingress {
    description     = "Relay ECS -> Valkey"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.relay.id]
  }
  tags = { Name = "${local.name}-valkey-sg" }
}
