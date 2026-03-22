variable "alarm_email_subscriptions" {
  description = "List of email addresses to subscribe to alarm SNS topic"
  type        = list(string)
  default     = []
}
