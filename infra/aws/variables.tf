# ---- REQUIRED inputs (no defaults — must be supplied; never invented) ----
variable "aws_region" {
  description = "Production AWS region for RoofSpan CP+Relay. HUMAN REQUIRED — do NOT default. ACM certs for the ALB are created in THIS region."
  type        = string
  validation {
    condition     = length(var.aws_region) > 0
    error_message = "aws_region must be set explicitly (e.g. us-east-1). No silent default."
  }
}

variable "dns_provider" {
  description = <<-EOT
    Where roofspan.io DNS is authoritative.
      "external" (DEFAULT) = DNS is hosted OUTSIDE Route53 (e.g. GoDaddy). Terraform does NOT create any
                 Route53 records and does NOT require a hosted zone. It still requests the ACM cert and
                 OUTPUTS the exact validation CNAMEs + endpoint CNAMEs the operator must add at the
                 external DNS provider (HUMAN REQUIRED). See scripts/README.md "External DNS".
      "route53"  = roofspan.io hosted zone lives in Route53; Terraform manages validation + A-alias records
                 automatically (requires route53_zone_id).
  EOT
  type        = string
  default     = "external"
  validation {
    condition     = contains(["external", "route53"], var.dns_provider)
    error_message = "dns_provider must be \"external\" (GoDaddy/other) or \"route53\"."
  }
}

variable "route53_zone_id" {
  description = "EXISTING roofspan.io Route53 hosted zone ID. Required ONLY when dns_provider = \"route53\". Leave empty for external DNS. Do NOT create a second zone."
  type        = string
  default     = ""
}

variable "control_plane_image" {
  description = "Full CP image reference by DIGEST or immutable release tag (e.g. <acct>.dkr.ecr.<region>.amazonaws.com/roofspan-control-plane@sha256:...). HUMAN builds/pushes first."
  type        = string
}

variable "relay_image" {
  description = "Full Relay image reference by DIGEST or immutable release tag. HUMAN builds/pushes first."
  type        = string
}

# ---- Config with sensible, documented defaults ----
variable "environment" {
  type    = string
  default = "production"
  validation {
    condition     = contains(["production", "dev"], var.environment)
    error_message = "environment must be 'production' or 'dev' (KISS — no staging/QA/DR hierarchy)."
  }
}

variable "domain" {
  type    = string
  default = "roofspan.io"
}
variable "cp_hostname" {
  type    = string
  default = "cp.roofspan.io"
}
variable "relay_hostname" {
  type    = string
  default = "relay.roofspan.io"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "az_count" {
  type    = number
  default = 2
}
variable "single_nat_gateway" {
  description = "true = ONE NAT GW (cost-conscious initial prod; single-AZ egress SPOF, documented). false = one NAT per AZ (HA egress, higher cost)."
  type        = bool
  default     = true
}

# ECS sizing (small/cost-conscious initial production; Relay must allow >1 task for Valkey multi-node).
variable "cp_desired_count" {
  type    = number
  default = 2
}
variable "cp_cpu" {
  type    = number
  default = 512
}
variable "cp_memory" {
  type    = number
  default = 1024
}
variable "relay_desired_count" {
  type    = number
  default = 2
}
variable "relay_cpu" {
  type    = number
  default = 512
}
variable "relay_memory" {
  type    = number
  default = 1024
}
variable "cp_max_count" {
  type    = number
  default = 6
}
variable "relay_max_count" {
  type    = number
  default = 6
}

variable "cp_container_port" {
  type    = number
  default = 8080
}
variable "relay_container_port" {
  type    = number
  default = 8080
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.small"
}
variable "rds_allocated_storage" {
  type    = number
  default = 20
}
variable "rds_max_allocated_storage" {
  type    = number
  default = 100
}
variable "rds_backup_retention_days" {
  type    = number
  default = 14
}
variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "valkey_node_type" {
  type    = string
  default = "cache.t4g.small"
}
variable "valkey_replicas" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 90
}

variable "alarm_sns_topic_arn" {
  description = "Optional existing SNS topic ARN for CloudWatch alarm notifications. Empty = no subscriptions wired."
  type        = string
  default     = ""
}
