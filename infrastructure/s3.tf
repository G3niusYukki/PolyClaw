# S3 Buckets for PolyClaw data storage
# Buckets: historical markets, order books, backtest results, and structured logs

locals {
  bucket_prefix = "polyclaw-data-${var.environment}"
  common_tags = {
    Project     = "polyclaw"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket" "polyclaw_data" {
  bucket = local.bucket_prefix

  tags = local.common_tags
}

resource "aws_s3_bucket_versioning" "polyclaw_data" {
  bucket = aws_s3_bucket.polyclaw_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "polyclaw_data" {
  bucket = aws_s3_bucket.polyclaw_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "polyclaw_data" {
  bucket = aws_s3_bucket.polyclaw_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rule: transition to IA after 30 days, Glacier after 1 year
resource "aws_s3_bucket_lifecycle_configuration" "polyclaw_data" {
  bucket = aws_s3_bucket.polyclaw_data.id

  rule {
    id     = "storage-lifecycle"
    status = "Enabled"

    filter {
      prefix = ""
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

# Structured logs bucket
resource "aws_s3_bucket" "polyclaw_logs" {
  bucket = "${local.bucket_prefix}-logs"

  tags = local.common_tags
}

resource "aws_s3_bucket_versioning" "polyclaw_logs" {
  bucket = aws_s3_bucket.polyclaw_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "polyclaw_logs" {
  bucket = aws_s3_bucket.polyclaw_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "polyclaw_logs" {
  bucket = aws_s3_bucket.polyclaw_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "polyclaw_logs" {
  bucket = aws_s3_bucket.polyclaw_logs.id

  rule {
    id     = "logs-lifecycle"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# CloudTrail trail for API call logging
resource "aws_s3_bucket" "polyclaw_cloudtrail" {
  count  = var.environment == "prod" ? 1 : 0
  bucket = "${local.bucket_prefix}-cloudtrail"

  tags = local.common_tags
}

resource "aws_cloudtrail" "polyclaw" {
  count = var.environment == "prod" ? 1 : 0
  name  = "polyclaw-cloudtrail"

  s3_bucket_name = aws_s3_bucket.polyclaw_cloudtrail[0].id
  is_multi_region_trail = false
  enable_logging = true

  event_selector {
    read_write_type = "All"
    include_management_events = true
  }
}
