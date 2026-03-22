# PolyClaw

PolyClaw is a guarded Polymarket auto-analysis and execution framework. It is designed around a closed loop:

1. Ingest markets from a provider
2. Enrich with evidence from news / research sources
3. Score opportunity + confidence
4. Apply risk controls
5. Create orders in paper mode or guarded live mode
6. Record positions, fills, and decisions for review

> Default mode is **paper trading**. Live execution is intentionally gated behind configuration and risk controls.

## Features

- Multi-strategy framework with `BaseStrategy` interface and `StrategyRegistry`
- Two built-in strategies: **EventCatalyst** (high-conviction events near resolution) and **LiquidityMomentum** (volume spike + breakout)
- Backtesting engine with walk-forward validation and performance reports
- Portfolio-level risk management: Kelly position sizing, event cluster tracking, circuit breakers
- Postgres persistence with Alembic migrations (SQLite for dev)
- Historical data ingestion pipeline with Lambda + EventBridge
- Terraform infrastructure (RDS, S3, Lambda, EventBridge, ECS Fargate, ALB, Secrets Manager, Grafana, CloudWatch Alarms, DR replication)
- Grafana dashboards (8 panels: system health, PnL, Sharpe, fill rate, latency, reconciliation)
- CloudWatch alarms (6 metrics with SNS routing)
- AlertRouter (Telegram/PagerDuty with severity-based routing)
- Scaling automation (auto stage advancement based on performance criteria)
- Market expansion with auto-candidate detection
- Slippage monitoring with excessive slippage alerts
- Fee optimization (platform fees + Polygon gas estimation)
- Anomaly detection (3-sigma PnL/volume/spread spikes)
- Operational runbook and DR test procedures
- GitHub Actions CI/CD (lint, type-check, test, migration, Terraform validate)
- Dockerfile (multi-stage, non-root) + Docker Compose
- Disaster recovery (cross-region S3 replication, RDS read replica failover)
- 400+ tests covering all core functionality

## Architecture

```
providers -> analysis -> strategies -> risk -> order planner -> approval gate -> executor -> storage -> API/reporting
```

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn polyclaw.api.main:app --reload
```

### CLI Commands

```bash
polyclaw tick        # Run full analysis + execution cycle
polyclaw backtest    # Run backtest with walk-forward validation
```

### API Endpoints

- `GET /health` — Health check
- `POST /scan` — Run market scan, create decisions
- `GET /markets` — List all cached markets
- `GET /candidates` — Ranked market candidates
- `GET /proposals` — Proposal previews
- `POST /proposals/persist` — Persist proposals to database
- `GET /proposal-records` — List persisted proposal records
- `POST /proposal-records/{id}/status` — Update proposal status
- `POST /proposals/{market_id}/materialize` — Convert proposal to Decision
- `GET /decisions` — List all decisions
- `POST /decisions/{id}/approve` — Approve a decision
- `POST /runner/tick` — Run full scan + execute-ready cycle
- `POST /execute-ready` — Execute all approved decisions
- `GET /positions` — Current positions
- `GET /audit-logs` — Audit trail
- `GET/POST /kill-switch` — Kill switch status and control

## Safe Defaults

- `EXECUTION_MODE=paper`
- `REQUIRE_APPROVAL=true`
- `AUTO_EXECUTE=false`
- `LIVE_TRADING_ENABLED=false`

## Key Environment Variables

- `DATABASE_URL` — SQLite dev default, Postgres for production
- `MARKET_SOURCE=sample|polymarket`
- `EXECUTION_MODE=paper|live`
- `REQUIRE_APPROVAL=true|false`
- `AUTO_EXECUTE=true|false`
- `LIVE_TRADING_ENABLED=true|false`
- `MIN_CONFIDENCE`, `MIN_EDGE_BPS`, `MAX_SPREAD_BPS`, `MIN_LIQUIDITY_USD`, `MAX_TOTAL_EXPOSURE_USD`, `MAX_POSITION_USD`

## Production Roadmap

See `docs/superpowers/specs/2026-03-22-production-roadmap-design.md` for the 3-month roadmap:
- Phase 1: Foundation ✅ (data infrastructure, multi-strategy, backtesting, portfolio risk)
- Phase 2: Execution ✅ (CTF integration, order management, reconciliation, shadow mode, ECS deployment)
- Phase 3: Production ✅ (observability, scaling, CI/CD, disaster recovery)

## Disclaimer

This software is for research and controlled automation. Prediction markets and crypto-linked systems carry significant financial and operational risk.
