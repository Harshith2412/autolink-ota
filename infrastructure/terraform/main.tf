# Optional AWS footprint for firmware artifacts and logs.
# (unverified: not planned or applied; no AWS credentials in the build environment.
#  `terraform validate` was not run. Review costs before `terraform apply`.)
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
}

provider "aws" { region = var.region }

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "autolink-ota"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

resource "aws_s3_bucket" "firmware" {
  bucket_prefix = "${var.project}-firmware-"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "firmware" {
  bucket = aws_s3_bucket.firmware.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "firmware" {
  bucket = aws_s3_bucket.firmware.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_public_access_block" "firmware" {
  bucket                  = aws_s3_bucket.firmware.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.firmware.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.firmware.arn, "${aws_s3_bucket.firmware.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/${var.project}/backend"
  retention_in_days = var.log_retention_days
}

# Least-privilege policy for the backend's runtime role: write/read firmware objects, write logs.
data "aws_iam_policy_document" "backend" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.firmware.arn}/firmware/*"]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.backend.arn}:*"]
  }
}

resource "aws_iam_policy" "backend" {
  name   = "${var.project}-backend"
  policy = data.aws_iam_policy_document.backend.json
}

output "firmware_bucket" { value = aws_s3_bucket.firmware.bucket }
output "log_group" { value = aws_cloudwatch_log_group.backend.name }
output "backend_policy_arn" { value = aws_iam_policy.backend.arn }
