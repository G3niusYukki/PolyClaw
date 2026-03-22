# Phase 1: Production Foundation — Implementation Plan

**Date:** 2026-03-22
**Branch:** `feat/phase1-production-foundation`
**Worktree:** `.worktrees/phase1-production-foundation/`
**Source:** `docs/superpowers/specs/2026-03-22-production-roadmap-design.md`

---

## Phase 1 Gate Criteria

Backtest Sharpe >1.2, max DD <15% for ≥2 strategies

---

## Week 1: Data Infrastructure

### 1.1 Migrate SQLite → Postgres
- [ ] Add `psycopg2-binary` dependency for Postgres
- [ ] Add `alembic` for database migrations
- [ ] Update `db.py` to support both SQLite (dev) and Postgres (prod) via `DATABASE_URL`
- [ ] Create initial Alembic migration
- [ ] Add `database_url` to `.env.example`

### 1.2 Provision RDS Postgres config
- [ ] Add `infrastructure/rds.tf` Terraform file for RDS Postgres (db.r6g.large)
- [ ] Document RDS connection in `docs/infrastructure.md`

### 1.3 S3 data bucket
- [ ] Add `infrastructure/s3.tf` Terraform file for S3 bucket with lifecycle policies
- [ ] Add `infrastructure/outputs.tf` with bucket name output

### 1.4 Historical backfill infrastructure
- [ ] Create `polyclaw/ingestion/backfill.py` — fetches historical markets from Polymarket Gamma API
- [ ] Create `polyclaw/ingestion/fetchers.py` — market, orderbook, trade fetchers
- [ ] Add `fetch_historical()` function that takes date range

### 1.5 Lambda ingestion function (code scaffold)
- [ ] Create `infrastructure/lambda/ingestion/` directory with `lambda_function.py`
- [ ] Create `infrastructure/lambda/ingestion/requirements.txt`
- [ ] Create `infrastructure/eventbridge.tf` with 3-min schedule rule
- [ ] Document Lambda setup in `docs/infrastructure.md`

### 1.6 Verification
- [ ] Run `pytest` — all tests pass
- [ ] Verify SQLite still works in dev mode
- [ ] `alembic upgrade head` runs successfully on fresh migration

---

## Week 2: Multi-Strategy Framework

### 2.1 BaseStrategy interface
- [ ] Create `polyclaw/strategies/base.py` with `BaseStrategy` abstract class
  - Methods: `compute_features()`, `generate_signals()`, `validate()`
  - Properties: `strategy_id`, `name`, `version`, `enabled`
- [ ] Create `polyclaw/strategies/registry.py` — `StrategyRegistry` singleton

### 2.2 Port existing heuristic to EventCatalyst strategy
- [ ] Create `polyclaw/strategies/event_catalyst.py`
- [ ] Move/adapt logic from `strategy.py`, `evidence.py`, `ranking.py` into strategy class
- [ ] Features: `days_to_resolution`, `event_category`, `news_sentiment`, `volume_surge_ratio`
- [ ] Strategy config: `min_days_to_resolution`, `max_days_to_resolution`, `min_confidence`

### 2.3 Implement LiquidityMomentum strategy
- [ ] Create `polyclaw/strategies/liquidity_momentum.py`
- [ ] Features: `volume_surge_ratio`, `liquidity_depth`, `price_momentum_24h`
- [ ] Entry: volume spike + price breaking out + sufficient depth
- [ ] Strategy config: `max_position_pct`, `max_drawdown_pct`, `max_daily_trades`

### 2.4 Feature computation pipeline
- [ ] Create `polyclaw/strategies/features.py` — `FeatureEngine` class
- [ ] Compute features from market snapshots: volume, spread, liquidity, momentum
- [ ] Add feature caching with TTL

### 2.5 Update AnalysisService for multi-strategy
- [ ] Update `services/analysis.py` to iterate over enabled strategies
- [ ] Aggregate signals from all strategies

### 2.6 Verification
- [ ] Run `pytest` — all tests pass
- [ ] Both strategies can be instantiated and generate signals
- [ ] `StrategyRegistry` correctly registers and retrieves strategies

---

## Week 3: Backtesting Engine

### 3.1 BacktestRunner
- [ ] Create `polyclaw/backtest/runner.py` — `BacktestRunner` class
- [ ] Event-driven simulation with historical market data
- [ ] Methods: `run()`, `add_strategy()`, `set_date_range()`
- [ ] Track: trades, positions, PnL, equity curve

### 3.2 Slippage model
- [ ] Create `polyclaw/backtest/slippage.py` — `SlippageModel` class
- [ ] Walk order book levels to estimate fill price
- [ ] Use volume and spread to calculate slippage

### 3.3 Walk-forward validation
- [ ] Create `polyclaw/backtest/walkforward.py` — `WalkForwardValidator`
- [ ] Split: 60-day train, 30-day test (configurable)
- [ ] Generate validation report with Sharpe, max DD, win rate

### 3.4 Performance reports
- [ ] Create `polyclaw/backtest/reports.py` — `PerformanceReport` class
- [ ] Metrics: Sharpe ratio, max drawdown, win rate, total trades, avg trade PnL
- [ ] Output: JSON and console summary

### 3.5 Backtest CLI command
- [ ] Add `polyclaw backtest` command to CLI
- [ ] Options: `--strategy`, `--start-date`, `--end-date`, `--train-days`, `--test-days`

### 3.6 Verification
- [ ] Run `polyclaw backtest` with EventCatalyst on 90-day sample data
- [ ] Report shows Sharpe ratio, max DD, win rate
- [ ] `pytest` — all tests pass

---

## Week 4: Portfolio Risk

### 4.1 PortfolioRiskEngine
- [ ] Create `polyclaw/risk/portfolio.py` — `PortfolioRiskEngine` class
- [ ] Portfolio-level limits: max correlated exposure, max concentration, max positions
- [ ] Methods: `evaluate()`, `check_limits()`, `calculate_portfolio_exposure()`

### 4.2 Correlation tracking by event cluster
- [ ] Create `polyclaw/risk/clusters.py` — `EventClusterTracker`
- [ ] Map markets to clusters (e.g., "2024-election", "fed-policy")
- [ ] Track exposure per cluster
- [ ] Max 30% correlated exposure per cluster

### 4.3 Kelly position sizing
- [ ] Create `polyclaw/risk/sizing.py` — `KellyPositionSizer` class
- [ ] Kelly fraction calculation with risk adjustment
- [ ] Fractional Kelly (quarter-Kelly) for conservatism

### 4.4 Circuit breakers
- [ ] Enhance `polyclaw/safety.py` with circuit breaker classes
- [ ] Global circuit breaker: portfolio DD >20%, daily loss >$500, data stale >15min
- [ ] Strategy-level circuit breaker: strategy DD >10%, >20% exec failure rate
- [ ] Auto-reset logic: strategy-level resets after 24h + review

### 4.5 Risk configuration
- [ ] Update `RISK_CONFIG.yaml` with portfolio and strategy-level limits
- [ ] Create `polyclaw/risk/config.py` to load and validate risk config

### 4.6 Verification
- [ ] Run `pytest` — all tests pass
- [ ] PortfolioRiskEngine correctly blocks trades exceeding limits
- [ ] Circuit breakers trigger on threshold violations
- [ ] Kelly sizing produces reasonable position sizes

---

## Final Verification
- [ ] All 4 weeks complete
- [ ] `pytest` — all tests pass
- [ ] Backtest reports available for both strategies
- [ ] Risk engine operational
- [ ] Phase 1 gate: verify strategy configs ready for backtest validation
