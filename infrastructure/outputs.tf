output "s3_data_bucket_name" {
  description = "Name of the main PolyClaw data S3 bucket"
  value       = aws_s3_bucket.polyclaw_data.id
}

output "s3_logs_bucket_name" {
  description = "Name of the PolyClaw logs S3 bucket"
  value       = aws_s3_bucket.polyclaw_logs.id
}

output "s3_bucket_prefix" {
  description = "Common S3 bucket name prefix"
  value       = local.bucket_prefix
}

output "rds_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.polyclaw.endpoint
}

output "rds_arn" {
  description = "RDS instance ARN"
  value       = aws_db_instance.polyclaw.arn
}

output "rds_security_group_id" {
  description = "RDS security group ID"
  value       = aws_security_group.polyclaw_rds.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = length(var.vpc_id) > 0 ? var.vpc_id : aws_vpc.polyclaw[0].id
}
