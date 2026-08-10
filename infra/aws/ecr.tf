resource "aws_ecr_repository" "control_plane" {
  name                 = "roofspan-control-plane"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.general.arn
  }
  tags = { Name = "roofspan-control-plane" }
}

resource "aws_ecr_repository" "relay" {
  name                 = "roofspan-relay"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.general.arn
  }
  tags = { Name = "roofspan-relay" }
}

locals {
  ecr_lifecycle = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 15 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 15 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "cp" {
  repository = aws_ecr_repository.control_plane.name
  policy     = local.ecr_lifecycle
}
resource "aws_ecr_lifecycle_policy" "relay" {
  repository = aws_ecr_repository.relay.name
  policy     = local.ecr_lifecycle
}
