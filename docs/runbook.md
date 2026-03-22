# PolyClaw Operational Runbook

This runbook provides actionable guidance for operating the PolyClaw trading system in production on AWS ECS Fargate.

---

## Deployment

### ECS Rolling Update

1. **Push the new image to ECR:**
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t polyclaw:<version> .
   docker tag polyclaw:<version> <account>.dkr.ecr.us-east-1.amazonaws.com/polyclaw:<version>
   docker push <account>.dkr.ecr.us-east-1.amazonaws.com/polyclaw:<version>
   ```

2. **Update the ECS task definition:**
   ```bash
   aws ecs update-service \
     --cluster polyclaw-production \
     --service polyclaw-<service> \
     --force-new-deployment \
     --region us-east-1
   ```
   Where `<service>` is one of: `ingestion`, `strategy`, `execution`, `monitor`.

3. **Monitor the rolling update:**
   ```bash
   aws ecs wait services-stable \
     --cluster polyclaw-production \
     --services polyclaw-ingestion,polyclaw-strategy,polyclaw-execution,polyclaw-monitor \
     --region us-east-1
   ```

4. **Verify the new task is running:**
   ```bash
   aws ecs describe-services \
     --cluster polyclaw-production \
     --services polyclaw-<service> \
     --query 'services[0].deployments' \
     --region us-east-1
   ```

### Rollback Procedure

If the new deployment causes issues, roll back to the previous task definition revision:

```bash
# List task definition revisions
aws ecs list-task-definitions \
  --family-prefix polyclaw-task \
  --sort DESC \
  --query 'taskDefinitionArns' \
  --region us-east-1

# Roll back to the previous revision (e.g., revision 12)
aws ecs update-service \
  --cluster polyclaw-production \
  --service polyclaw-<service> \
  --task-definition polyclaw-task:<previous-revision> \
  --region us-east-1
```

For critical incidents, immediately enable the kill switch before rolling back:
```bash
# Enable kill switch (blocks all trading)
curl -X POST https://api.polyclaw.example/kill-switch/enable \
  -d "reason=rollback emergency"

# Then roll back
aws ecs update-service \
  --cluster polyclaw-production \
  --service polyclaw-<service> \
  --task-definition polyclaw-task:<previous-revision> \
  --region us-east-1
```

---

## Monitoring

### CloudWatch Logs Insights

Query logs across all services:

```sql
# Recent errors across all services
fields @timestamp, @message, @logStream
| filter @message like /ERROR|CRITICAL|WARN/
| sort @timestamp desc
| limit 100

# Ingestion service errors
fields @timestamp, @message
| filter @logStream like /ingestion/
| filter @message like /ERROR/
| sort @timestamp desc
| limit 50

# Execution service order failures
fields @timestamp, @message
| filter @logStream like /execution/
| filter @message like /order.*failed|submission.*error/
| sort @timestamp desc
| limit 50

# Reconciliation drift alerts
fields @timestamp, @message
| filter @message like /reconciliation|drift/
| sort @timestamp desc
| limit 50

# Anomaly detection alerts
fields @timestamp, @message
| filter @message like /anomaly|ANOMALY|spike/
| sort @timestamp desc
| limit 50

# Circuit breaker triggers
fields @timestamp, @message
| filter @message like /circuit_breaker|triggered/
| sort @timestamp desc
| limit 50
```

### CloudWatch Log Groups

| Service | Log Group |
|---------|-----------|
| Ingestion Lambda | `/ecs/polyclaw-ingestion` |
| Strategy Engine | `/ecs/polyclaw-strategy` |
| Execution Service | `/ecs/polyclaw-execution` |
| Monitor / API | `/ecs/polyclaw-monitor` |
| Lambda (scheduled) | `/aws/lambda/polyclaw-ingestion` |
| ECS Cluster | `/ecs/polyclaw-production` |

### Grafana Dashboard

Access the Grafana dashboard at `https://grafana.example/d/polyclaw-overview`.

Key panels:
- **PnL Overview**: Daily PnL, cumulative PnL, 30-day rolling stats
- **Order Volume**: Orders submitted/filled/cancelled per hour
- **Anomaly Alerts**: Timeline of detected anomalies by type
- **Data Freshness**: Age of latest market data ingestion
- **Health Checks**: Component-level health status (database, API, CTF, kill switch)
- **Position Reconciliation**: Drift detection timeline and auto-close events

---

## Alert Response

### Severity Levels

| Severity | Response Time | Definition |
|----------|-------------|------------|
| **INFO** | Acknowledge | Routine operational notifications. No immediate action required. |
| **WARNING** | Investigate within 1 hour | Degraded performance, elevated risk metrics, or minor discrepancies. |
| **CRITICAL** | Respond within 15 minutes | System health failure, kill switch triggered, reconciliation drift > $5, PnL spike anomaly, or circuit breaker blown. |

### Alert Response Procedure

#### CRITICAL Alerts

1. **Acknowledge** the alert in PagerDuty/SNS subscription.
2. **Check the kill switch status** immediately:
   ```bash
   curl https://api.polyclaw.example/kill-switch
   ```
   If the kill switch is NOT active and trading is causing the issue, enable it:
   ```bash
   curl -X POST https://api.polyclaw.example/kill-switch/enable \
     -d "reason=critical_alert_response"
   ```
3. **Identify the root cause** using CloudWatch Logs Insights (see queries above).
4. **Engage the on-call engineer** if the issue cannot be resolved within 15 minutes.
5. **Document the incident** in the incident tracker.
6. **Resolve**: Once fixed, disable the kill switch only after confirming the root cause is resolved.

#### WARNING Alerts

1. **Acknowledge** the alert.
2. **Investigate** within 1 hour:
   - Check CloudWatch metrics for the affected component
   - Review recent deployment changes
   - Check market conditions (unusual volume/spread on Polymarket)
3. **Escalate** to CRITICAL if the issue worsens or persists > 1 hour.

#### INFO Alerts

1. **Acknowledge** in the alert dashboard.
2. **Log** for post-incident review if unexpected.

---

## Kill Switch

The kill switch is the primary safety control that halts all trading immediately.

### Activate

```bash
# Via API
curl -X POST https://api.polyclaw.example/kill-switch/enable \
  -d "reason=<your_reason>"

# Via AWS CLI (emergency)
aws ecs update-service \
  --cluster polyclaw-production \
  --service polyclaw-execution \
  --desired-count 0 \
  --region us-east-1
```

### Deactivate

```bash
curl -X POST https://api.polyclaw.example/kill-switch/disable \
  -d "reason=resolved_after_review"
```

### What It Blocks

When the kill switch is active:
- All new order submissions are blocked at the execution layer
- The runner service skips the execute-ready step
- Strategy analysis continues normally (no trading occurs)
- Shadow mode continues (no real orders submitted)
- The `/kill-switch` endpoint reflects the active state
- The health check endpoint reports kill_switch status as `unhealthy`

---

## Manual Execution

### Run a Single Tick Manually via CLI

```bash
# Activate virtual environment
source .venv/bin/activate

# Run a full tick (scan + analysis)
polyclaw tick

# Run with verbose logging
POLYCLAW_LOG_LEVEL=DEBUG polyclaw tick

# Run scan only (no execution)
polyclaw tick --scan-only

# Run a single strategy
polyclaw tick --strategy event_catalyst

# Run backtest
polyclaw backtest --strategy event_catalyst --start 2026-01-01 --end 2026-03-01
```

### Manual Order Submission

```bash
# Via API — materialize a proposal and approve it
# Step 1: Get a tradable proposal
curl https://api.polyclaw.example/proposals

# Step 2: Materialize the proposal as a decision
curl -X POST https://api.polyclaw.example/proposals/<market_id>/materialize

# Step 3: List the new decision
curl https://api.polyclaw.example/decisions

# Step 4: Approve the decision
curl -X POST https://api.polyclaw.example/decisions/<decision_id>/approve

# Step 5: Execute
curl -X POST https://api.polyclaw.example/execute-ready
```

---

## Database Access

### Connect via Bastion Host

```bash
# Start port forwarding through the bastion
ssh -L 5433:<rds-endpoint>:5432 \
  -i ~/.ssh/polyclaw-bastion.pem \
  ec2-user@bastion.example.com \
  -N

# In another terminal, connect via psql
psql -h localhost -p 5433 -U polyclaw -d polyclaw_prod
```

### Common psql Commands

```sql
-- Current positions
SELECT * FROM positions WHERE is_open = true;

-- Recent orders
SELECT * FROM orders ORDER BY submitted_at DESC LIMIT 50;

-- Audit log (last 100 entries)
SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100;

-- Kill switch history
SELECT * FROM audit_logs WHERE action = 'kill_switch' ORDER BY created_at DESC;

-- Reconciliation drift events
SELECT * FROM audit_logs WHERE action LIKE 'reconciliation%' ORDER BY created_at DESC;

-- Anomaly alerts
SELECT * FROM audit_logs WHERE action LIKE 'anomaly%' ORDER BY created_at DESC;

-- Market data freshness
SELECT market_id, title, fetched_at FROM markets ORDER BY fetched_at DESC LIMIT 20;
```

### RDS Endpoint

Retrieve from AWS Secrets Manager or SSM Parameter Store:
```bash
aws ssm get-parameter --name /polyclaw/production/rds/endpoint --region us-east-1
```

---

## Log Locations

| Component | CloudWatch Log Group |
|-----------|---------------------|
| Ingestion Lambda | `/aws/lambda/polyclaw-ingestion` |
| Strategy Engine (ECS) | `/ecs/polyclaw-strategy` |
| Execution Service (ECS) | `/ecs/polyclaw-execution` |
| Monitor/API (ECS) | `/ecs/polyclaw-monitor` |
| EventBridge Scheduler | `/aws/events/polyclaw-scheduler` |
| Lambda function logs | `/aws/lambda/polyclaw-*` |

### Log Retention

- All log groups: 30 days retention
- Audit log (PostgreSQL): 90 days (older entries purged by a nightly job)

---

## Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| **On-Call Engineer (Primary)** | PagerDuty rotation | Level 1 |
| **On-Call Engineer (Secondary)** | PagerDuty rotation | Level 2 |
| **Infrastructure / DevOps** | `#ops-alerts` Slack channel | Infrastructure issues |
| **Trading Risk Owner** | `#risk-alerts` Slack channel | PnL anomalies, reconciliation drift |
| **Engineering Lead** | `#engineering-oncall` | Production outages > 30 min |

### Escalation Path

1. **Primary on-call** responds to CRITICAL alerts within 15 minutes
2. If no response in 15 minutes, **secondary on-call** is paged
3. If unresolved after 30 minutes, **engineering lead** is notified
4. For any kill-switch-related incident, document in the incident tracker after resolution

### Emergency Channels

- **Slack**: `#polyclaw-incidents` (primary), `#polyclaw-alerts` (all alerts)
- **PagerDuty**: CRITICAL alerts route here
- **Email**: `oncall@polyclaw.example` (non-urgent only)
