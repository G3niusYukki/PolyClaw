# =============================================================================
# Disaster Recovery Infrastructure
# =============================================================================
# This module provisions resources for DR: cross-region S3 replication,
# RDS read replica for failover, and CloudWatch alarms for DR triggers.
#
# RTO (Recovery Time Objective): < 30 minutes
# RPO (Recovery Point Objective): < 1 hour (7-day RDS retention)

locals {
  dr_tags = merge(local.common_tags, {
    Component = "disaster-recovery"
  })
}

# =============================================================================
# S3 Cross-Region Replication
# =============================================================================
# Note: Replication is configured on the primary buckets in s3.tf.
# This module adds the replication configuration for the data bucket.

resource "aws_s3_bucket_replication_configuration" "polyclaw_data_replication" {
  bucket = aws_s3_bucket.polyclaw_data.id
  role   = aws_iam_role.s3_replication.arn

  rule {
    id     = "replicate-to-dr"
    status = "Enabled"

    filter {}

    destination {
      bucket        = aws_s3_bucket.polyclaw_data_dr.id
      storage_class = "STANDARD_IA"

      encryption_configuration {
        replica_kms_key_id = aws_kms_key.s3_replication.arn
      }
    }

    delete_marker_replication {
      status = "Enabled"
    }
  }
}

# DR region bucket (us-west-2)
resource "aws_s3_bucket" "polyclaw_data_dr" {
  bucket = "polyclaw-data-${var.environment}-dr"

  tags = local.dr_tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "polyclaw_data_dr" {
  bucket = aws_s3_bucket.polyclaw_data_dr.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "polyclaw_data_dr" {
  bucket = aws_s3_bucket.polyclaw_data_dr.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "polyclaw_data_dr" {
  bucket = aws_s3_bucket.polyclaw_data_dr.id

  versioning_configuration {
    status = "Enabled"
  }
}

# DR logs bucket
resource "aws_s3_bucket" "polyclaw_logs_dr" {
  bucket = "polyclaw-data-${var.environment}-dr-logs"

  tags = local.dr_tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "polyclaw_logs_dr" {
  bucket = aws_s3_bucket.polyclaw_logs_dr.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "polyclaw_logs_dr" {
  bucket = aws_s3_bucket.polyclaw_logs_dr.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =============================================================================
# IAM Role for S3 Replication
# =============================================================================

resource "aws_iam_role" "s3_replication" {
  name = "polyclaw-s3-replication-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
      }
    ]
  })

  tags = local.dr_tags
}

resource "aws_iam_policy" "s3_replication_policy" {
  name = "polyclaw-s3-replication-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetReplicationConfiguration",
          "s3:ListBucket",
        ]
        Resource = aws_s3_bucket.polyclaw_data.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ReplicateObject",
          "s3:ReplicateDelete",
          "s3:ObjectOwnerOverrideToBucketOwner",
          "s3:ReplicateTags",
        ]
        Resource = "${aws_s3_bucket.polyclaw_data_dr.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ]
        Resource = aws_kms_key.s3_replication.arn
      },
    ]
  })

  tags = local.dr_tags
}

resource "aws_iam_role_policy_attachment" "s3_replication" {
  role       = aws_iam_role.s3_replication.name
  policy_arn = aws_iam_policy.s3_replication_policy.arn
}

# =============================================================================
# KMS Key for Replication Encryption
# =============================================================================

resource "aws_kms_key" "s3_replication" {
  description             = "KMS key for S3 cross-region replication encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = local.dr_tags
}

resource "aws_kms_alias" "s3_replication" {
  name          = "alias/polyclaw-s3-replication"
  target_key_id = aws_kms_key.s3_replication.key_id
}

# =============================================================================
# RDS Read Replica (for DR failover)
# =============================================================================

resource "aws_db_instance" "polyclaw_replica" {
  count                        = var.environment == "prod" ? 1 : 0
  identifier                   = "polyclaw-db-replica"
  engine                       = "postgres"
  engine_version               = "16.4"
  instance_class               = var.db_instance_class
  replicate_source_db          = aws_db_instance.polyclaw.identifier
  db_subnet_group_name         = aws_db_subnet_group.polyclaw.name
  vpc_security_group_ids       = [aws_security_group.polyclaw_rds.id]
  publicly_accessible          = false
  storage_encrypted            = true
  performance_insights_enabled = true
  auto_minor_version_upgrade   = false

  tags = merge(local.dr_tags, {
    Role = "read-replica"
  })
}

# =============================================================================
# CloudWatch Alarms for DR
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "rds_high_cpu" {
  count               = var.environment == "prod" ? 1 : 0
  alarm_name          = "polyclaw-rds-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "RDS CPU utilization above 80%"
  alarm_actions       = [aws_sns_topic.dr_alerts[0].arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.polyclaw.identifier
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_low_storage" {
  count               = var.environment == "prod" ? 1 : 0
  alarm_name          = "polyclaw-rds-low-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Minimum"
  threshold           = 5368709120 # 5GB
  alarm_description   = "RDS free storage below 5GB"
  alarm_actions       = [aws_sns_topic.dr_alerts[0].arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.polyclaw.identifier
  }
}

resource "aws_sns_topic" "dr_alerts" {
  count = var.environment == "prod" ? 1 : 0
  name  = "polyclaw-dr-alerts"

  tags = local.dr_tags
}

resource "aws_sns_topic_policy" "dr_alerts" {
  count = var.environment == "prod" ? 1 : 0
  arn   = aws_sns_topic.dr_alerts[0].arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "cloudwatch.amazonaws.com"
        }
        Action   = "sns:Publish"
        Resource = aws_sns_topic.dr_alerts[0].arn
      }
    ]
  })
}

# =============================================================================
# DR Outputs
# =============================================================================

output "dr_rto_minutes" {
  description = "Recovery Time Objective in minutes"
  value       = 30
}

output "dr_rpo_minutes" {
  description = "Recovery Point Objective in minutes"
  value       = 60
}

output "rds_replica_id" {
  description = "RDS read replica identifier (for DR promotion)"
  value       = try(aws_db_instance.polyclaw_replica[0].id, "not-configured")
}

output "dr_s3_data_bucket" {
  description = "DR region S3 data bucket name"
  value       = aws_s3_bucket.polyclaw_data_dr.id
}

output "dr_s3_logs_bucket" {
  description = "DR region S3 logs bucket name"
  value       = aws_s3_bucket.polyclaw_logs_dr.id
}

output "dr_alarm_topic_arn" {
  description = "ARN of the DR alerts SNS topic"
  value       = try(aws_sns_topic.dr_alerts[0].arn, "not-configured")
}

output "rds_backup_retention_days" {
  description = "RDS backup retention period in days"
  value       = aws_db_instance.polyclaw.backup_retention_period
}
