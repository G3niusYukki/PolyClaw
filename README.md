# PolyClaw

PolyClaw is a guarded Polymarket auto-analysis and execution framework. It is designed around a closed loop:

1. Ingest markets from a provider
2. Enrich with evidence from news / research sources
3. Score opportunity + confidence
4. Apply risk controls
5. Create orders in paper mode or guarded live mode (via Polymarket CTF on Polygon)
6. Record positions, fills, and decisions for review

> Default mode is **paper trading**. Live execution is intentionally gated behind configuration, startup prerequisites, and risk controls.

## Live Trading Readiness

PolyClaw is at **readiness level 8.5/10** for live trading. Key capabilities:

- **Confirmed CTF ABI selectors** — `createOrder=0x6f652e1a`, `cancelOrder=0x0fdb031d`, `getBalance=0x4e11e440`
- **Real on-chain position queries** — `_query_ctf_positions()` via `eth_call` to CTF `getBalance`
- **Startup prerequisite validation** — `LiveTradingPrerequisites` checks RPC, selectors, contract address, balances before enabling live mode
- **Reconciliation gating** — live trading blocked if Polymarket API or CTF chain positions are unreachable
- **Closed-loop smoke tests** — `test_live_smoke.py` exercises full pipeline (run manually with `-m live_manual`)
- **Shadow mode** — validate signals against real outcomes before live capital at risk

See `SAFETY_CHECKLIST.md` and `docs/superpowers/plans/2026-03-23-ctf-confident-plan.md` for pre-live requirements.

## Features

- Multi-strategy framework with `BaseStrategy` interface and `StrategyRegistry`
- Two built-in strategies: **EventCatalyst** (high-conviction events near resolution) and **LiquidityMomentum** (volume spike + breakout)
- Backtesting engine with walk-forward validation and performance reports
- Portfolio-level risk management: Kelly position sizing, event cluster tracking, circuit breakers
- **Live CTF trading via Polygon** — confirmed ABI selectors, EIP-1559 transactions, fill status polling, on-chain position queries
- **Startup prerequisite guard** — `LiveTradingPrerequisites` validates RPC, selectors, balances before enabling live mode
- **Reconciliation gating** — blocks live trading when Polymarket API or CTF chain position sources are unavailable
- **Shadow mode** — simulate execution against real market outcomes before live capital at risk
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
- `GET /orders` / `GET /orders/{id}` — Order tracking
- `GET /positions` — Current positions
- `GET /audit-logs` — Audit trail
- `GET/POST /kill-switch` — Kill switch status and control
- `POST /reconciliation/run` / `GET /reconciliation/report` — Position reconciliation
- `GET /shadow/results` / `GET /shadow/accuracy` / `GET /shadow/positions` — Shadow mode
- `POST /shadow/reset` / `GET/POST /shadow/mode` — Shadow mode control
- `GET /reports/pnl` / `GET /reports/attribution` / `GET /reports/daily` — PnL and attribution reports
- `GET /health/detailed` — Detailed health check (DB, Polymarket API, CTF, data freshness, kill switch)

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
