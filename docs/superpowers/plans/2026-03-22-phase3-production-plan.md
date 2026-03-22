# Phase 3: Production — Implementation Plan

**Date:** 2026-03-22
**Branch:** `feat/phase3-production`
**Worktree:** `.worktrees/phase3-production/`
**Source:** `docs/superpowers/specs/2026-03-22-production-roadmap-design.md`

---

## Phase 3 Gate Criteria

Live trading profitable for 2+ weeks, 99.5% uptime, DR tested

---

## Week 10: Observability

### 10.1 Grafana Dashboards
- [ ] Create `infrastructure/grafana.tf` with Grafana provisioning config
  - Dashboard JSON definitions for: System Health, Strategy Performance, Execution Metrics, Portfolio PnL
  - Datasources: CloudWatch, Postgres (via Grafana Postgres plugin or direct)
- [ ] Create `infrastructure/monitoring.tf` with CloudWatch metrics definitions
  - Custom metrics: signal_generation_latency, order_submission_latency, data_freshness_seconds, unrealized_pnl, strategy_sharpe_7d, reconciliation_error_pct, order_fill_rate
- [ ] Create `polyclaw/monitoring/metrics.py` with `MetricsCollector` class
  - Emit custom CloudWatch metrics from strategy/execution/risk modules
  - Use `boto3` CloudWatch client

### 10.2 CloudWatch Alarms
- [ ] Create `infrastructure/alarms.tf` with CloudWatch alarms
  - `system_health_alarm` — API errors >5/min
  - `data_freshness_alarm` — data age >10 minutes
  - `portfolio_pnl_alarm` — unrealized_pnl <-$500 (CRITICAL)
  - `strategy_sharpe_alarm` — strategy_sharpe_7d <0.5 for 3 consecutive days
  - `reconciliation_error_alarm` — reconciliation_error_pct >1%
  - `order_fill_rate_alarm` — order_fill_rate <80%
  - All alarms route to SNS topic

### 10.3 Telegram/PagerDuty Integration
- [ ] Create `polyclaw/monitoring/alerts.py` with `AlertRouter` class
  - `send_alert(severity, title, message, channels)` — routes to Telegram, PagerDuty, or email
  - `AlertSeverity`: INFO, WARNING, CRITICAL
  - Telegram: send via bot API (configurable chat ID)
  - PagerDuty: Events API v2 for critical escalation
  - Email: via SMTP or SES (configurable)
- [ ] Create `polyclaw/monitoring/channels.py` with channel implementations
  - `TelegramChannel`, `PagerDutyChannel`, `EmailChannel`
- [ ] Integrate `AlertRouter` into existing notification flow (replace basic `notifications.py`)

### 10.4 PnL Attribution Reports
- [ ] Create `polyclaw/monitoring/pnl.py` with `PnLReporter` class
  - `daily_pnl(session) -> dict`: PnL breakdown by strategy, by market, by side
  - `attribution(session, date_range) -> dict`: contribution of each strategy to portfolio PnL
  - `equity_curve(session) -> list[dict]`: daily equity curve with drawdown
- [ ] Add `GET /reports/pnl` and `GET /reports/attribution` API endpoints
- [ ] Create `polyclaw/monitoring/daily_report.py` with `DailyReportGenerator`
  - Generate daily report: PnL summary, trade count, win rate, Sharpe, top positions
  - Send via Telegram as INFO alert every UTC midnight

### 10.5 Verification
- [ ] Run `pytest` — all tests pass
- [ ] `AlertRouter` correctly routes alerts by severity
- [ ] PnL reporter calculates accurate attribution

---

## Week 11: Scaling

### 11.1 Scale Automation
- [ ] Create `polyclaw/scaling/manager.py` with `ScalingManager` class
  - `get_current_stage() -> int`: from StagedPositionSizer
  - `evaluate_scale() -> tuple[bool, str]`: evaluate if profitable enough to scale
  - Scale criteria: 2+ weeks profitable, Sharpe >1.0, max DD <15%, no circuit breakers
  - `scale_to(stage: int)`: trigger stage advancement via StagedPositionSizer
  - Scale path: shadow → 10% → 25% → 50% → 100% (one stage at a time)
- [ ] Create `polyclaw/scaling/evaluator.py` with `PerformanceEvaluator` class
  - `is_profitable(days: int = 14) -> bool`: check if profitable over N days
  - `sharpe_acceptable(threshold: float = 1.0) -> bool`
  - `drawdown_acceptable(threshold: float = 0.15) -> bool`
  - `no_active_circuit_breakers() -> bool`

### 11.2 Market Expansion
- [ ] Enhance `polyclaw/execution/whitelist.py` with auto-expansion logic
  - `evaluate_expansion_candidates(markets: list[MarketSnapshot]) -> list[str]`
  - Candidates: liquidity >$50K, spread <200 bps, volume >$10K, not already whitelisted
  - Auto-add candidates to whitelist after manual review (flag for approval)
- [ ] Create `polyclaw/scaling/expansion.py` with `MarketExpander` class
  - `suggest_expansion(session) -> list[MarketExpansionSuggestion]`
  - `apply_expansion(market_id: str)`: add to whitelist
  - Log all expansion decisions to audit log

### 11.3 Slippage Monitoring
- [ ] Create `polyclaw/scaling/slippage_monitor.py` with `SlippageMonitor` class
  - `track_fill(expected_price: float, actual_price: float, market_id: str, size_usd: float)`
  - `get_slippage_stats(window_days: int = 7) -> dict`: avg slippage, max slippage, by market, by size bucket
  - Alert if avg slippage >0.5% or slippage trend increasing
  - Store slippage records in DB for analysis

### 11.4 Fee Optimization
- [ ] Create `polyclaw/scaling/fee_calculator.py` with `FeeCalculator` class
  - Calculate trading fees per market: Polymarket fee (typically 0% on AMM, 1% on order book)
  - Calculate gas fees: estimate from Polygon gas prices
  - `total_cost(order_spec: OrderSpec) -> FeeBreakdown`: platform fee + gas + slippage
  - Factor fees into position sizing and strategy PnL calculations
- [ ] Integrate into `ExecutionService` and `BacktestRunner` for accurate PnL

### 11.5 Verification
- [ ] Run `pytest` — all tests pass
- [ ] Scale automation correctly evaluates stage advancement criteria
- [ ] Slippage monitor tracks and alerts on excessive slippage

---

## Week 12: Monitoring Refinements

### 12.1 Anomaly Detection
- [ ] Create `polyclaw/monitoring/anomaly.py` with `AnomalyDetector` class
  - `detect_pnl_spike(session) -> bool`: flag if daily PnL > 3 std deviations from mean
  - `detect_volume_anomaly(market_id: str) -> bool`: flag unusual volume spikes
  - `detect_spread_anomaly(market_id: str) -> bool`: flag unusual spread widening
  - Simple statistical approach: rolling mean + std deviation over 30-day window
  - Emit CRITICAL alert on anomaly detection

### 12.2 Operational Runbook
- [ ] Create `docs/runbook.md` with operational procedures:
  - Deploying updates (ECS rolling update)
  - Restarting services after failure
  - Viewing logs (CloudWatch Insights queries)
  - Checking Grafana dashboards
  - Responding to alerts (by severity level)
  - Manual kill switch activation
  - Emergency rollback procedure

### 12.3 Health Checks Enhancement
- [ ] Create `polyclaw/monitoring/health.py` with `HealthChecker` class
  - `check() -> HealthStatus`: overall system health
  - Checks: database connectivity, Polymarket API responsiveness, CTF contract reachable, data freshness
  - `GET /health/detailed` endpoint returning full health breakdown
- [ ] Integrate health checks into ECS task definitions (ALB health checks already configured)

### 12.4 Verification
- [ ] Run `pytest` — all tests pass
- [ ] Anomaly detector correctly identifies statistical outliers
- [ ] Health checker returns accurate status for all components

---

## Week 13: Hardening

### 13.1 CI/CD Pipeline
- [ ] Create `.github/workflows/ci.yml`:
  - On push/PR: lint (ruff or flake8), type check (mypy), pytest with coverage
  - Coverage gate: must exceed 80%
  - On merge to main: run Alembic migration check, Terraform validate
  - On release tag: deploy to ECS via `aws ecs update-service`
- [ ] Create `.github/workflows/deploy.yml`:
  - Deploy to staging on PR merge
  - Deploy to production on release tag with manual approval
  - ECS task definition update with new image tag
- [ ] Create `Dockerfile`:
  - Python 3.12 slim base
  - Multi-stage build: deps → app
  - Health check endpoint
- [ ] Create `.github/workflows/ecr-repo.tf` (placeholder for ECR repository creation)

### 13.2 Alembic Migrations (Already Implemented in Phase 1)
- [ ] Verify `alembic upgrade head` runs cleanly on fresh DB
- [ ] Add migration testing to CI (dry-run on ephemeral DB)
- [ ] Document migration workflow in `docs/runbook.md`

### 13.3 Disaster Recovery Testing
- [ ] Create `docs/dr-test-procedure.md`:
  - RDS failover test: promote read replica, update connection string
  - S3 restore test: verify data can be restored from backup
  - ECS recovery test: verify auto-restart of failed tasks
  - Kill switch test: verify all execution stops when triggered
  - Database restore test: restore from latest snapshot to new instance
- [ ] Create `polyclaw/dr/recovery.py` with `DisasterRecoveryManager` class
  - `restore_from_backup(backup_type: str)`: orchestrate full DB restore
  - `verify_data_integrity() -> bool`: verify restored data matches expected state
  - `switch_read_replica() -> str`: promote read replica to primary

### 13.4 Verification
- [ ] Run `pytest` — all tests pass
- [ ] CI pipeline runs successfully (lint, type check, tests)
- [ ] Dockerfile builds successfully
- [ ] All Terraform files pass `terraform validate`

---

## Final Verification
- [ ] All 4 weeks complete
- [ ] `pytest` — all tests pass
- [ ] CI/CD pipeline operational
- [ ] All Terraform validated
- [ ] Documentation complete (runbook, DR procedure)
