locals {
  use_route53 = var.dns_provider == "route53"
}

# ACM cert for cp + relay hostnames. Requested in BOTH DNS modes (ALB is regional -> cert is in
# var.aws_region; this is NOT the us-east-1 CloudFront cert for downloads.roofspan.io, which is
# separate and left untouched).
resource "aws_acm_certificate" "main" {
  domain_name               = var.cp_hostname
  subject_alternative_names = [var.relay_hostname]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
    # Guard: route53 mode must supply a zone id (external mode leaves it empty on purpose).
    precondition {
      condition     = var.dns_provider != "route53" || length(var.route53_zone_id) > 0
      error_message = "route53_zone_id is required when dns_provider = \"route53\"."
    }
  }
  tags = { Name = "${local.name}-cert" }
}

# ---- ROUTE53 MODE ONLY: Terraform auto-creates validation + endpoint records ----
# In external DNS mode (GoDaddy) NONE of the Route53 resources below are created.
resource "aws_route53_record" "cert_validation" {
  for_each = local.use_route53 ? {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  } : {}
  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_route53_record" "cp" {
  count   = local.use_route53 ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.cp_hostname
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "relay" {
  count   = local.use_route53 ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.relay_hostname
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

# ---- Certificate issuance wait (BOTH modes) ----
# route53 mode: waits on the auto-created validation records.
# external mode: waits until the operator adds the validation CNAMEs at GoDaddy and ACM issues.
#   The HTTPS listener (alb.tf) references this resource, so it will not come up until the cert is
#   ISSUED. For external DNS this implies a two-stage apply (Stage 1: create cert -> read the
#   acm_validation_records output -> add CNAMEs at GoDaddy -> ACM issues; Stage 2: full apply).
resource "aws_acm_certificate_validation" "main" {
  certificate_arn = aws_acm_certificate.main.arn
  validation_record_fqdns = local.use_route53 ? [
    for r in aws_route53_record.cert_validation : r.fqdn
    ] : [
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.resource_record_name
  ]
  timeouts {
    create = "90m" # generous window for the manual GoDaddy step in external DNS mode
  }
}
