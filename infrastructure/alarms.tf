# CloudWatch Alarms for PolyClaw monitoring

resource "aws_sns_topic" "alarms" {
  name = "${var.environment}-polyclaw-alarms"
  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count     = var.alarm_email_subscriptions != [] ? length(var.alarm_email_subscriptions) : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email_subscriptions[count.index]
}

# System Health Alarm — API errors > 5 per minute
resource "aws_cloudwatch_metric_alarm" "system_health" {
  alarm_name          = "${var.environment}-polyclaw-api-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "APIErrors"
  namespace           = "PolyClaw"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "PolyClaw API errors exceed 5 per minute for 5 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    Service = "polyclaw-api"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

# Data Freshness Alarm — data stale for more than 10 minutes
resource "aws_cloudwatch_metric_alarm" "data_freshness" {
  alarm_name          = "${var.environment}-polyclaw-data-freshness"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "data_freshness_seconds"
  namespace           = "PolyClaw"
  period              = 60
  statistic           = "Maximum"
  threshold           = 600
  alarm_description   = "PolyClaw market data is older than 10 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    Service = "polyclaw-ingestion"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

# Portfolio PnL Alarm — unrealized PnL drops below -$500 (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "portfolio_pnl" {
  alarm_name          = "${var.environment}-polyclaw-portfolio-pnl"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "unrealized_pnl"
  namespace           = "PolyClaw"
  period              = 300
  statistic           = "Maximum"
  threshold           = -500
  alarm_description   = "PolyClaw portfolio unrealized PnL is below -$500 — CRITICAL"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    Service = "polyclaw-risk"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
    Severity    = "CRITICAL"
  }
}

# Strategy Sharpe Alarm — 7-day Sharpe ratio below 0.5
resource "aws_cloudwatch_metric_alarm" "strategy_sharpe" {
  alarm_name          = "${var.environment}-polyclaw-strategy-sharpe"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "strategy_sharpe_7d"
  namespace           = "PolyClaw"
  period              = 3600
  statistic           = "Average"
  threshold           = 0.5
  alarm_description   = "PolyClaw 7-day Sharpe ratio is below 0.5"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    Service = "polyclaw-strategy"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
    Severity    = "WARNING"
  }
}

# Reconciliation Error Alarm — error rate above 1%
resource "aws_cloudwatch_metric_alarm" "reconciliation_error" {
  alarm_name          = "${var.environment}-polyclaw-reconciliation-error"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "reconciliation_error_pct"
  namespace           = "PolyClaw"
  period              = 300
  statistic           = "Maximum"
  threshold           = 1.0
  alarm_description   = "PolyClaw reconciliation error rate exceeds 1%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    Service = "polyclaw-reconciliation"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
    Severity    = "WARNING"
  }
}

# Order Fill Rate Alarm — fill rate below 80%
resource "aws_cloudwatch_metric_alarm" "order_fill_rate" {
  alarm_name          = "${var.environment}-polyclaw-order-fill-rate"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "order_fill_rate"
  namespace           = "PolyClaw"
  period              = 900
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "PolyClaw order fill rate is below 80%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    Service = "polyclaw-execution"
  }

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
    Severity    = "WARNING"
  }
}
