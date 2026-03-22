# Lambda function for PolyClaw data ingestion

resource "aws_iam_role" "ingestion_lambda" {
  name = "polyclaw-ingestion-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "ingestion_lambda_policy" {
  name = "polyclaw-ingestion-lambda-policy"
  role = aws_iam_role.ingestion_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.polyclaw_data.arn,
          "${aws_s3_bucket.polyclaw_data.arn}/*",
          aws_s3_bucket.polyclaw_logs.arn,
          "${aws_s3_bucket.polyclaw_logs.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_lambda_function" "ingestion" {
  function_name = "polyclaw-ingestion"
  description   = "PolyClaw historical data ingestion Lambda"
  role          = aws_iam_role.ingestion_lambda.arn

  filename         = "lambda/ingestion/deployment.zip"
  source_code_hash = filebase64sha256("lambda/ingestion/deployment.zip")
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 300 # 5 minutes
  memory_size      = 256

  environment {
    variables = {
      DATABASE_URL   = var.db_password != "" ? "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.polyclaw.endpoint}/${var.db_name}" : "sqlite:///./polyclaw.db"
      ENVIRONMENT    = var.environment
      S3_BUCKET_DATA = aws_s3_bucket.polyclaw_data.id
      S3_BUCKET_LOGS = aws_s3_bucket.polyclaw_logs.id
    }
  }

  vpc_config {
    subnet_ids         = aws_db_subnet_group.polyclaw.subnet_ids
    security_group_ids = [aws_security_group.polyclaw_rds.id]
  }

  depends_on = [
    aws_iam_role_policy.ingestion_lambda_policy,
    aws_cloudwatch_event_target.ingestion_lambda,
  ]

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "ingestion_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.ingestion.function_name}"
  retention_in_days = 14

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}
