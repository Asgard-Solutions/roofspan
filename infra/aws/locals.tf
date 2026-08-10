data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name    = "roofspan-${var.environment}"
  azs     = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  account = data.aws_caller_identity.current.account_id

  # /20 subnets carved from the VPC /16: public, private-app, private-data per AZ.
  public_subnets  = [for i in range(var.az_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  app_subnets     = [for i in range(var.az_count) : cidrsubnet(var.vpc_cidr, 4, i + 4)]
  data_subnets    = [for i in range(var.az_count) : cidrsubnet(var.vpc_cidr, 4, i + 8)]
  cp_domain_names = [var.cp_hostname, var.relay_hostname]
}
