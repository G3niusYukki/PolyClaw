# Grafana Dashboard Provisioning for PolyClaw

resource "aws_s3_bucket" "grafana_dashboards" {
  bucket = "${var.environment}-polyclaw-grafana-dashboards"
  tags = {
    Project     = "polyclaw"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_object" "dashboard_json" {
  bucket  = aws_s3_bucket.grafana_dashboards.id
  key     = "polyclaw-dashboard.json"
  content = local.polyclaw_dashboard_json
  etag    = md5(local.polyclaw_dashboard_json)
}

# Grafana Dashboard JSON Provisioner
# NOTE: This assumes Grafana is running as a sidecar or managed service.
# If using Grafana in ECS, use the grafana/grafana container with provisioning.

# Inline JSON dashboard definition (alternative to S3 file provisioner)
# This can be used with the Grafana HTTP API or file-based provisioning.
locals {
  polyclaw_dashboard_json = jsonencode({
    title    = "PolyClaw Production Dashboard"
    tags     = ["polyclaw", "production"]
    timezone = "browser"
    refresh  = "30s"
    panels = [
      {
        id      = 1
        title   = "System Health"
        type    = "stat"
        gridPos = { h = 4, w = 6, x = 0, y = 0 }
        targets = [
          {
            refId        = "A"
            expr         = "sum(rate(pyclaw_api_errors_total[5m]))"
            legendFormat = "API Errors/s"
          }
        ]
      },
      {
        id      = 2
        title   = "Data Freshness"
        type    = "gauge"
        gridPos = { h = 4, w = 6, x = 6, y = 0 }
        targets = [
          {
            refId        = "A"
            expr         = "polyclaw_data_freshness_seconds"
            legendFormat = "Data Age (s)"
          }
        ]
      },
      {
        id      = 3
        title   = "Unrealized PnL"
        type    = "stat"
        gridPos = { h = 4, w = 6, x = 12, y = 0 }
        targets = [
          {
            refId        = "A"
            expr         = "polyclaw_unrealized_pnl"
            legendFormat = "Unrealized PnL ($)"
          }
        ]
        fieldConfig = {
          defaults = {
            thresholds = {
              mode = "absolute"
              steps = [
                { color = "red", value = null },
                { color = "yellow", value = -500 },
                { color = "green", value = 0 }
              ]
            }
          }
        }
      },
      {
        id      = 4
        title   = "Strategy Sharpe (7d)"
        type    = "stat"
        gridPos = { h = 4, w = 6, x = 18, y = 0 }
        targets = [
          {
            refId        = "A"
            expr         = "polyclaw_strategy_sharpe_7d"
            legendFormat = "Sharpe Ratio"
          }
        ]
      },
      {
        id      = 5
        title   = "Order Fill Rate"
        type    = "gauge"
        gridPos = { h = 4, w = 8, x = 0, y = 4 }
        targets = [
          {
            refId        = "A"
            expr         = "polyclaw_order_fill_rate"
            legendFormat = "Fill Rate (%)"
          }
        ]
      },
      {
        id      = 6
        title   = "Reconciliation Error Rate"
        type    = "gauge"
        gridPos = { h = 4, w = 8, x = 8, y = 4 }
        targets = [
          {
            refId        = "A"
            expr         = "polyclaw_reconciliation_error_pct"
            legendFormat = "Error Rate (%)"
          }
        ]
      },
      {
        id      = 7
        title   = "Signal Generation Latency"
        type    = "graph"
        gridPos = { h = 8, w = 12, x = 0, y = 8 }
        targets = [
          {
            refId        = "A"
            expr         = "histogram_quantile(0.95, rate(polyclaw_signal_generation_latency_seconds_bucket[5m]))"
            legendFormat = "p95 Latency"
          },
          {
            refId        = "B"
            expr         = "histogram_quantile(0.50, rate(polyclaw_signal_generation_latency_seconds_bucket[5m]))"
            legendFormat = "p50 Latency"
          }
        ]
      },
      {
        id      = 8
        title   = "Order Submission Latency"
        type    = "graph"
        gridPos = { h = 8, w = 12, x = 12, y = 8 }
        targets = [
          {
            refId        = "A"
            expr         = "histogram_quantile(0.95, rate(polyclaw_order_submission_latency_seconds_bucket[5m]))"
            legendFormat = "p95 Latency"
          },
          {
            refId        = "B"
            expr         = "histogram_quantile(0.50, rate(polyclaw_order_submission_latency_seconds_bucket[5m]))"
            legendFormat = "p50 Latency"
          }
        ]
      }
    ]
  })
}

# Store dashboard JSON in S3 for Grafana file provisioner
resource "aws_s3_bucket_object" "grafana_dashboard_inline" {
  bucket  = aws_s3_bucket.grafana_dashboards.id
  key     = "dashboard-inline.json"
  content = local.polyclaw_dashboard_json
}

# Grafana provisioning configuration (for file-based provisioning)
resource "local_file" "grafana_provisioning_dashboard" {
  content = jsonencode({
    apiVersion = 1
    providers = [
      {
        name                  = "PolyClaw Dashboards"
        orgId                 = 1
        folder                = "PolyClaw"
        folderUid             = "polyclaw"
        type                  = "file"
        disableDeletion       = false
        updateIntervalSeconds = 10
        options = {
          path = "/var/lib/grafana/dashboards/polyclaw"
        }
      }
    ]
  })
  filename = "${path.module}/grafana-provisioning-dashboards.yaml"
}
