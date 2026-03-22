# AWS Secrets Manager resources for PolyClaw secrets
# Stores sensitive credentials used by the application

locals {
  common_tags = {
    Project     = "polyclaw"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# CTF Private Key — the wallet private key for signing CTF transactions on Polygon
resource "aws_secretsmanager_secret" "ctf_private_key" {
  name                    = "polyclaw/ctf/private_key"
  description             = "Private key for CTF wallet on Polygon (used for signing transactions)"
  recovery_window_in_days = 7

  tags = merge(local.common_tags, {
    SecretType = "credentials"
    Component  = "ctf"
  })
}

resource "aws_secretsmanager_secret_version" "ctf_private_key" {
  secret_id = aws_secretsmanager_secret.ctf_private_key.id
  # The actual secret value should be set via AWS Console, CLI, or another secret source
  # terraform apply will not set the actual private key value
  secret_string = jsonencode({
    private_key = "" # Placeholder — set via aws_secretsmanager_secret_version after initial creation
  })
}

# Polymarket API Key — for authenticated Polymarket API calls
resource "aws_secretsmanager_secret" "polymarket_api_key" {
  name                    = "polyclaw/polymarket/api_key"
  description             = "Polymarket API key for authenticated market data and order operations"
  recovery_window_in_days = 7

  tags = merge(local.common_tags, {
    SecretType = "api_key"
    Component  = "polymarket"
  })
}

resource "aws_secretsmanager_secret_version" "polymarket_api_key" {
  secret_id = aws_secretsmanager_secret.polymarket_api_key.id
  secret_string = jsonencode({
    api_key = "" # Placeholder
  })
}

# Telegram Bot Token — for sending execution and alert notifications
resource "aws_secretsmanager_secret" "telegram_bot_token" {
  name                    = "polyclaw/telegram/bot_token"
  description             = "Telegram bot token for sending notifications to trading channels"
  recovery_window_in_days = 7

  tags = merge(local.common_tags, {
    SecretType = "credentials"
    Component  = "telegram"
  })
}

resource "aws_secretsmanager_secret_version" "telegram_bot_token" {
  secret_id = aws_secretsmanager_secret.telegram_bot_token.id
  secret_string = jsonencode({
    bot_token = "" # Placeholder
  })
}

# Resource policy: allow Lambda functions to read secrets
data "aws_iam_policy_document" "secrets_read" {
  statement {
    sid    = "AllowLambdaReadSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.ctf_private_key.arn,
      aws_secretsmanager_secret.polymarket_api_key.arn,
      aws_secretsmanager_secret.telegram_bot_token.arn,
    ]
  }
}

resource "aws_secretsmanager_secret_policy" "secrets_read" {
  name       = "polyclaw-secrets-read-policy"
  secret_arn = aws_secretsmanager_secret.ctf_private_key.arn
  policy     = data.aws_iam_policy_document.secrets_read.json
}
