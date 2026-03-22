# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PolyClaw is a guarded Polymarket auto-analysis and execution framework. It ingests prediction markets, scores opportunities with evidence and strategy engines, applies risk controls, and can create orders in paper or guarded live mode.

**Default mode is paper trading.** Live execution is gated behind configuration and explicit safety controls.

## Development Commands

```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the API server (development)
uvicorn polyclaw.api.main:app --reload

# Run the CLI tick (full analysis + execution cycle)
polyclaw tick

# Run backtest with walk-forward validation
polyclaw backtest --strategy event_catalyst

# Run all tests
pytest

# Run tests with coverage
pytest --cov=polyclaw --cov-report=term-missing

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture

```
providers -> analysis -> strategies -> risk -> order planner -> approval gate -> executor -> storage -> API/reporting
```

### Core Modules

| Module | Purpose |
|--------|---------|
| `polyclaw/providers/` | Pluggable provider interfaces (MarketProvider, EvidenceProvider, ExecutionProvider) |
| `polyclaw/services/analysis.py` | Orchestrates scanning, ranking, evidence, strategies, and risk |
| `polyclaw/services/runner.py` | Orchestrates full tick cycle (scan + execute-ready) |
| `polyclaw/services/execution.py` | Handles order approval and execution dispatch |
| `polyclaw/strategies/` | Multi-strategy framework: BaseStrategy, StrategyRegistry, EventCatalyst, LiquidityMomentum |
| `polyclaw/strategies/features.py` | FeatureEngine with TTL caching for strategy features |
| `polyclaw/backtest/` | Backtesting: BacktestRunner, SlippageModel, WalkForwardValidator, PerformanceReport |
| `polyclaw/ranking.py` | MarketRanker — scores markets by liquidity, volume, spread, time to close |
| `polyclaw/evidence.py` | HeuristicEvidenceEngine — builds evidence from market characteristics |
| `polyclaw/risk/` | Risk management package: RiskEngine, PortfolioRiskEngine, EventClusterTracker, KellyPositionSizer, RiskConfig |
| `polyclaw/safety.py` | Kill switch, audit logging, GlobalCircuitBreaker, StrategyCircuitBreaker |
| `polyclaw/ingestion/` | Data ingestion: MarketFetcher, OrderBookFetcher, TradeFetcher, BackfillRunner |
| `polyclaw/execution/` | Execution package: OrderStateMachine, OrderType/OrderSpec, PriceBandValidator, RetryExecutor, OrderTracker, StagedPositionSizer, MarketWhitelist |
| `polyclaw/shadow/` | Shadow mode: ShadowModeEngine, SignalAccuracyMonitor, ThresholdTuner, LiveTransitionManager |
| `polyclaw/reconciliation/` | Reconciliation: ReconciliationService, DiscrepancyDetector, DriftAlerts |
| `polyclaw/monitoring/` | Observability: MetricsCollector, AlertRouter, TelegramChannel, PagerDutyChannel, PnLReporter, DailyReportGenerator, AnomalyDetector, HealthChecker |
| `polyclaw/scaling/` | Scaling: ScalingManager, PerformanceEvaluator, MarketExpander, SlippageMonitor, FeeCalculator |
| `polyclaw/dr/` | Disaster recovery: DisasterRecoveryManager (snapshot restore, replica switch, data integrity) |
| `polyclaw/workflow.py` | ProposalWorkflowService — persists proposals, manages statuses |
| `polyclaw/repositories.py` | Data access layer (upsert_market, create_decision, record_order_and_position) |
| `polyclaw/secrets.py` | AWS Secrets Manager client with env var fallback |
| `polyclaw/api/main.py` | FastAPI application with all REST endpoints |
| `alembic/` | Database migrations (Postgres/SQLite) |
| `infrastructure/` | Terraform for AWS (RDS, S3, Lambda, EventBridge, ECS, ALB, Secrets, Grafana, CloudWatch Alarms, DR) |

### Key Patterns

- **Strategy Framework** — `strategies/base.py` defines `BaseStrategy` ABC; `strategies/registry.py` manages enabled strategies
- **Provider Protocol** — `providers/base.py` defines `MarketProvider`, `EvidenceProvider`, `ExecutionProvider` protocols
- **Service Layer** — `services/` modules orchestrate business logic
- **Repository Pattern** — `repositories.py` wraps SQLAlchemy session operations
- **Domain Dataclasses** — `domain.py` defines `MarketSnapshot`, `EvidenceItem`, `DecisionProposal`
- **ORM Models** — `models.py` defines SQLAlchemy models (Market, Decision, Order, Position, AuditLog, ProposalRecord, ShadowResult, TradingStageRecord, MarketWhitelistRecord)
- **Risk Hierarchy** — `risk/__init__.py` (market-level RiskEngine) → `risk/portfolio.py` (portfolio-level) → `safety.py` (circuit breakers)
- **Execution Pipeline** — `execution/orders.py` (types) → `execution/price_bands.py` (validation) → `execution/retry.py` (retry) → `providers/ctf.py` (submission) → `execution/tracker.py` (tracking)
- **Shadow Mode** — `shadow/mode.py` (simulate execution) → `shadow/accuracy.py` (track accuracy) → `shadow/tuning.py` (tune thresholds) → `shadow/transition.py` (go live)
- **Monitoring Pipeline** — `metrics.py` (CloudWatch emission) → `alerts.py` (severity routing) → `channels.py` (Telegram/PagerDuty)
- **Scaling Pipeline** — `evaluator.py` (performance criteria) → `manager.py` (stage control) → `expansion.py` (market whitelist expansion)

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `POST /scan` | Run market scan, create decisions |
| `GET /markets` | List all cached markets |
| `GET /candidates` | Ranked market candidates |
| `GET /proposals` | Proposal previews |
| `POST /proposals/persist` | Persist proposals to database |
| `GET /proposal-records` | List persisted proposal records |
| `POST /proposal-records/{id}/status` | Update proposal status |
| `POST /proposals/{market_id}/materialize` | Convert proposal to Decision |
| `GET /decisions` | List all decisions |
| `POST /decisions/{id}/approve` | Approve a decision |
| `POST /runner/tick` | Run full scan + execute-ready cycle |
| `POST /execute-ready` | Execute all approved decisions |
| `GET /orders`, `GET /orders/{id}` | Order tracking |
| `GET /positions` | Current positions |
| `GET /audit-logs` | Audit trail |
| `GET/POST /kill-switch` | Kill switch status and control |
| `POST /reconciliation/run`, `GET /reconciliation/report` | Reconciliation |
| `GET /shadow/results`, `GET /shadow/accuracy`, `GET /shadow/positions` | Shadow mode |
| `POST /shadow/reset`, `GET/POST /shadow/mode` | Shadow mode control |
| `GET /reports/pnl`, `GET /reports/attribution`, `GET /reports/daily` | PnL and attribution reports |
| `GET /health/detailed` | Detailed health check (DB, Polymarket API, CTF, data freshness, kill switch) |

## Safety Controls

The system has multiple safety layers. All default to conservative values:
- `EXECUTION_MODE=paper` — paper by default, live requires explicit config
- `REQUIRE_APPROVAL=true` — decisions need manual approval before execution
- `AUTO_EXECUTE=false` — execution never happens automatically
- `LIVE_TRADING_ENABLED=false` — live mode is gated
- `SHADOW_MODE_ENABLED=true` — shadow mode enabled by default
- Kill switch blocks all execution when enabled
- `GlobalCircuitBreaker` — triggers on portfolio DD >20%, daily loss >$500, data stale >15min, exec failure >20%
- `StrategyCircuitBreaker` — triggers on strategy DD >10%, auto-resets after 24h + manual review
- `PriceBandValidator` — rejects orders >2% deviation from reference price
- Risk engine rejects trades on stale data, low liquidity, excessive spread, exposure overflow
- `MarketWhitelist` — default deny, only whitelisted markets eligible for live trading
- `StagedPositionSizer` — live trading scales through stages (shadow → 10% → 25% → 50% → 100%)
- Reconciliation auto-closes positions if drift >$10

See `RISK_CONFIG.yaml` for default risk thresholds and `SAFETY_CHECKLIST.md` for pre-live checks.

## Configuration

All settings come from environment variables (see `.env.example`). Key settings:
- `DATABASE_URL` — SQLite dev default, Postgres for production (e.g., `postgresql://user:pass@host:5432/polyclaw`)
- `MARKET_SOURCE=sample|polymarket` — data source toggle
- `EXECUTION_MODE=paper|live` — execution mode
- `REQUIRE_APPROVAL=true|false` — approval gate
- `AUTO_EXECUTE=true|false` — auto-execute approved decisions
- `LIVE_TRADING_ENABLED=true|false` — enable live trading
- Risk thresholds: `MIN_CONFIDENCE`, `MIN_EDGE_BPS`, `MAX_SPREAD_BPS`, `MIN_LIQUIDITY_USD`, `MAX_TOTAL_EXPOSURE_USD`, `MAX_POSITION_USD`

## Infrastructure

Terraform configs in `infrastructure/` for AWS deployment:
- `rds.tf` — RDS Postgres (db.t4g.medium)
- `s3.tf` — Data buckets with lifecycle policies
- `lambda.tf` + `lambda/ingestion/` — Lambda ingestion function
- `eventbridge.tf` — 3-minute ingestion schedule
- `secrets.tf` — AWS Secrets Manager for CTF keys, API keys, Telegram tokens
- `ecs.tf` — ECS Fargate cluster (4 services: ingestion, strategy, execution, monitor)
- `alb.tf` — Application Load Balancer with path-based routing
- `ecs-task-iam.tf` — IAM roles for ECS task execution
- `alarms.tf` — CloudWatch alarms (6 metrics) with SNS routing
- `grafana.tf` — Grafana dashboard provisioning
- `dr.tf` — Disaster recovery (cross-region S3 replication, RDS read replica)
- `outputs.tf` — bucket names, RDS endpoint, VPC IDs

CI/CD in `.github/workflows/`:
- `ci.yml` — lint (ruff), type-check (mypy), test (pytest with coverage ≥80%), alembic migration, terraform validate
- `deploy.yml` — Docker build to ECR, ECS task definition update, staging on main, production on release tag

Docker: `Dockerfile` (multi-stage, non-root) and `docker-compose.yml` (polyclaw + postgres)
