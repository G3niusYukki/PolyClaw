# EventBridge rule for scheduled ingestion Lambda trigger
# Runs every 3 minutes to keep market data fresh

resource "aws_cloudwatch_event_rule" "ingestion_schedule" {
  name                = "polyclaw-ingestion-schedule"
  description         = "Trigger PolyClaw ingestion Lambda every 3 minutes"
  schedule_expression = "rate(3 minutes)"
  is_enabled          = true

  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_event_target" "ingestion_lambda" {
  target_id = "polyclaw-ingestion-lambda"
  rule      = aws_cloudwatch_event_rule.ingestion_schedule.name
  arn       = aws_lambda_function.ingestion.arn
  input     = jsonencode({ "source": "aws.events", "detail-type": "Scheduled Event" })
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingestion_schedule.arn
}
