# ---------------------------------------------------------------------------
# IAM Roles for ECS Task Execution and Task Runtime
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Task Execution Role — used to pull images and write logs
# Permissions: ECR, CloudWatch Logs, Secrets Manager
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_task_execution_assume_role" {
  statement {
    effect = "Allow"
    principals = {
      Service = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "ecs_task_execution_role" {
  name               = "${var.environment}-polyclaw-ecs-task-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_execution_assume_role.json

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_policy" {
  name = "${var.environment}-polyclaw-ecs-task-execution-policy"
  role = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/ecs/${var.environment}/polyclaw/*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = [
          aws_secretsmanager_secret.polyclaw_db.arn,
          "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.environment}/polyclaw/*",
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Task Role — used at runtime by ECS containers
# Permissions: DynamoDB, S3, RDS (read/write positions, decisions)
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    effect = "Allow"
    principals = {
      Service = ["ecs-tasks.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "ecs_task_role" {
  name               = "${var.environment}-polyclaw-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "ecs_task_policy" {
  name = "${var.environment}-polyclaw-ecs-task-policy"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:*:table/${var.environment}-polyclaw-*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.environment}-polyclaw-data/*",
          "arn:aws:s3:::${var.environment}-polyclaw-data",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "rds-db:connect",
        ]
        Resource = "arn:aws:rds-db:${var.aws_region}:*:dbuser:*/*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = [
          aws_secretsmanager_secret.polyclaw_db.arn,
          "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.environment}/polyclaw/*",
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Secrets Manager secret version — allow ECS task to access DB credentials
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret_version" "polyclaw_db" {
  secret_id     = aws_secretsmanager_secret.polyclaw_db.id
  secret_string = var.db_password == "" ? jsonencode({ "url" = "placeholder-set-in-env" }) : jsonencode({ "url" = var.database_url })
}

# ---------------------------------------------------------------------------
# CloudWatch Logs — enable ECS container log ingestion
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "cloudwatch_logs_policy" {
  statement {
    Effect = "Allow"
    Action = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/ecs/${var.environment}/polyclaw/*"
  }
}

resource "aws_iam_role_policy" "cloudwatch_logs_policy" {
  name   = "${var.environment}-polyclaw-cloudwatch-logs"
  role   = aws_iam_role.ecs_task_execution_role.id
  policy = data.aws_iam_policy_document.cloudwatch_logs_policy.json
}
