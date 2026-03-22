# PolyClaw Production Roadmap Design

**Date:** 2026-03-22
**Status:** Draft
**Author:** Claude Code
**Scope:** 3-month roadmap to transform PolyClaw from research MVP to production trading system

---

## 1. Executive Summary

This document specifies the design for transforming PolyClaw from a research MVP into a production-grade autonomous trading system capable of long-term unattended operation on Polymarket.

### Current State Assessment

PolyClaw v0.1.0 is a functional MVP with:
- Pluggable market providers (Polymarket Gamma API)
- Heuristic evidence engine (keyword-based scoring)
- Single-strategy decision engine with simple edge calculation
- Paper execution provider only
- SQLite persistence
- Basic risk controls (spread, liquidity, exposure caps)
- Manual approval gates and kill switch primitives

### Target State (End of Month 3)

A production system with:
- Historical data warehouse (90+ days) with 3-minute snapshot granularity
- Multi-strategy framework with independent configuration and risk limits
- Validated backtesting with walk-forward analysis
- Real Polymarket execution via CTF (Conditional Tokens Framework)
- Order state machine with full lifecycle management
- Portfolio-level risk controls with correlation tracking
- Shadow mode for pre-live validation
- Staged live deployment starting at 10% size
- Comprehensive monitoring, alerting, and observability
- Disaster recovery and operational runbooks

### Success Criteria

| Metric | Target |
|--------|--------|
| System uptime | 99.5% |
| Data latency | <7 minutes |
| Reconciliation accuracy | 99.9% |
| Signal accuracy (shadow) | >60% |
| Portfolio Sharpe (live) | >1.0 |
| Max drawdown | <20% |
| Mean time to recovery | <4 hours |

---

## 2. Constraints & Requirements

### Business Constraints

- **Initial capital:** $5K-$25K (small scale)
- **Max drawdown tolerance:** 20% (moderate risk)
- **Strategy focus:** Multi-strategy ensemble
- **Infrastructure:** AWS (RDS Postgres, ECS Fargate)

### Functional Requirements

1. **Data Collection:** Capture market snapshots, order book, trades, and events every 3-4 minutes
2. **Strategy Research:** Support 3+ strategies with independent backtesting and validation
3. **Risk Management:** Portfolio-level limits with correlation tracking and circuit breakers
4. **Execution:** Real order submission with state tracking and reconciliation
5. **Monitoring:** Real-time alerts for system health, PnL, and risk limits
6. **Recovery:** Automatic restart with state restoration after failure

### Non-Functional Requirements

1. **Availability:** 99.5% uptime during market hours
2. **Latency:** Signal generation <30 seconds; order submission <5 seconds
3. **Durability:** Zero data loss for trade records; 4-hour RPO for market data
4. **Security:** Private keys in AWS Secrets Manager; encrypted at rest and in transit
5. **Observability:** All decisions logged with full provenance (strategy version, features, market state)

---

## 3. Architecture

### 3.1 High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ECS Fargate Cluster                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │  Ingestion  │  │  Strategy   │  │  Execution  │  │  Monitor   │ │   │
│  │  │   Service   │  │   Engine    │  │   Service   │  │  Service   │ │   │
│  │  │  (2 tasks)  │  │  (2 tasks)  │  │  (2 tasks)  │  │ (1 task)   │ │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘ │   │
│  │         │                │                │               │        │   │
│  │         └────────────────┴────────────────┴───────────────┘        │   │
│  │                              │                                      │   │
│  │                         ┌────┴────┐                                 │   │
│  │                         │   ALB   │                                 │   │
│  │                         └────┬────┘                                 │   │
│  └──────────────────────────────┼──────────────────────────────────────┘   │
│                                 │                                           │
│  ┌──────────────────────────────┼──────────────────────────────────────┐   │
│  │                              ▼                                      │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │              RDS Postgres (db.r6g.large)                    │   │   │
│  │  │  ├─ market_snapshots (time-series, partitioned)            │   │   │
│  │  │  ├─ order_book_levels (time-series)                        │   │   │
│  │  │  ├─ trades (time-series)                                    │   │   │
│  │  │  ├─ strategies (configuration)                              │   │   │
│  │  │  ├─ decisions (audit trail)                                 │   │   │
│  │  │  ├─ orders (order lifecycle)                                │   │   │
│  │  │  ├─ positions (portfolio state)                             │   │   │
│  │  │  └─ audit_logs (system events)                              │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                    │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │  ElastiCache Redis (cache.r6g.large)                        │   │   │
│  │  │  ├─ Feature cache                                           │   │   │
│  │  │  ├─ Rate limiting                                           │   │   │
│  │  │  └─ Session store                                           │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │  S3 Bucket (polyclaw-data)                                         │   │
│  │  ├─ historical/markets/YYYY/MM/DD/snapshots.parquet               │   │
│  │  ├─ historical/orderbook/YYYY/MM/DD/levels.parquet                │   │
│  │  ├─ backtest/results/<strategy_id>/<run_id>/report.json           │   │
│  │  ├─ logs/ingestion/YYYY/MM/DD/HH.jsonl.gz                         │   │
│  │  └─ snapshots/db/ (RDS automated backups)                         │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │  AWS Secrets Manager                                               │   │
│  │  ├─ polyclaw/polymarket/private_key (CTF wallet)                   │   │
│  │  ├─ polyclaw/telegram/bot_token                                    │   │
│  │  └─ polyclaw/pagerduty/integration_key                             │   │
│  └────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘

External APIs:
- Polymarket Gamma API (markets, events)
- Polymarket CTF (order submission, positions)
- Polygon RPC (blockchain confirmation)
- Telegram (alerts)
- PagerDuty (escalation)
```

### 3.2 Component Breakdown

#### 3.2.1 Ingestion Service

**Responsibility:** Fetch and store market data from Polymarket

**Key Functions:**
- `fetch_markets()`: Get active markets from Gamma API
- `fetch_orderbook()`: Get best bid/ask for each market
- `fetch_trades()`: Get recent trades for price discovery
- `persist_snapshot()`: Store to RDS and S3

**Scaling:** 2 Fargate tasks with leader election; EventBridge triggers every 3 minutes

**Data Retention:**
- RDS: 30 days hot (frequent queries)
- S3: 2 years cold (backtesting, audit)

#### 3.2.2 Strategy Engine

**Responsibility:** Generate trading signals from market data

**Key Functions:**
- `compute_features()`: Calculate technical/fundamental features
- `generate_signals()`: Run all enabled strategies
- `aggregate_signals()`: Combine signals into portfolio allocation
- `validate_signals()`: Check against backtest performance

**Strategies:**

1. **LiquidityMomentum**
   - Features: volume_surge_ratio, liquidity_depth, price_momentum
   - Logic: Enter when volume spikes + price breaking out + sufficient depth
   - Edge: Captures information-driven moves with exit liquidity

2. **EventCatalyst**
   - Features: days_to_resolution, event_category, news_sentiment
   - Logic: Trade high-conviction events approaching resolution
   - Edge: Time decay and information asymmetry near deadlines

3. **MeanReversion**
   - Features: z_score_24h, volatility_percentile, spread_percentile
   - Logic: Fade extreme moves when spread is tight
   - Edge: Overreaction correction in liquid markets

#### 3.2.3 Execution Service

**Responsibility:** Submit and track orders on Polymarket

**Key Functions:**
- `submit_order()`: Create and submit CTF order
- `track_order()`: Poll for fill updates
- `reconcile_positions()`: Compare system vs exchange positions
- `cancel_order()`: Handle timeout or risk-triggered cancellation

**Order State Machine:**

```
┌─────────┐   submit()    ┌───────────┐   venue ack    ┌─────────────┐
│ CREATED │──────────────→│ SUBMITTED │───────────────→│ ACKNOWLEDGED│
└─────────┘               └───────────┘                └──────┬──────┘
                                                              │
        ┌─────────────────────────────────────────────────────┤
        │                       fill event                    │
        ▼                                                     ▼
┌───────────────┐   complete    ┌─────────┐         ┌───────────────┐
│ PARTIAL_FILL  │──────────────→│ FILLED  │         │  CANCELING    │
└───────────────┘               └─────────┘         └───────┬───────┘
                                                            │ cancel ack
                                                            ▼
                                                    ┌───────────────┐
                                                    │   CANCELED    │
                                                    └───────────────┘
```

#### 3.2.4 Monitor Service

**Responsibility:** Health checks, alerting, and observability

**Key Functions:**
- `check_system_health()`: Verify all services responding
- `check_data_freshness()`: Alert on stale market data
- `check_pnl_limits()`: Trigger kill switch on drawdown
- `send_alert()`: Route alerts by severity (Telegram → Email → PagerDuty)

**Alert Severity Levels:**

| Level | Channel | Response Time | Examples |
|-------|---------|---------------|----------|
| INFO | Telegram | n/a | Daily PnL summary |
| WARNING | Telegram + Email | 1 hour | Strategy underperforming |
| CRITICAL | All + PagerDuty | 15 min | Kill switch triggered, data stale |

---

## 4. Data Model

### 4.1 Reference Tables

```sql
-- Markets reference table
CREATE TABLE markets (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(128) UNIQUE NOT NULL,
    title VARCHAR(512) NOT NULL,
    description TEXT,
    category VARCHAR(128),
    event_key VARCHAR(256),
    resolution_source VARCHAR(256),  -- URL for resolution criteria
    closes_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Event clusters for correlation tracking
CREATE TABLE event_clusters (
    id SERIAL PRIMARY KEY,
    cluster_key VARCHAR(256) UNIQUE NOT NULL,  -- e.g., "2024-election", "fed-policy"
    name VARCHAR(256) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Market to cluster mapping (many-to-many)
CREATE TABLE market_clusters (
    market_id VARCHAR(128) REFERENCES markets(market_id),
    cluster_key VARCHAR(256) REFERENCES event_clusters(cluster_key),
    confidence DECIMAL(3,2) DEFAULT 1.0,  -- How strongly this market belongs to cluster
    PRIMARY KEY (market_id, cluster_key)
);
```

### 4.2 Time-Series Tables (Partitioned by Month)

```sql
-- Market snapshots captured every 3 minutes
CREATE TABLE market_snapshots (
    id BIGSERIAL,
    market_id VARCHAR(128) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    yes_price DECIMAL(10,8) NOT NULL,
    no_price DECIMAL(10,8) NOT NULL,
    best_bid_yes DECIMAL(10,8),
    best_ask_yes DECIMAL(10,8),
    spread_bps INTEGER NOT NULL,
    liquidity_usd DECIMAL(18,4) NOT NULL,
    volume_24h DECIMAL(18,4) NOT NULL,
    outstanding_shares DECIMAL(18,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, captured_at)
) PARTITION BY RANGE (captured_at);

-- Order book depth (top 5 levels)
CREATE TABLE order_book_levels (
    id BIGSERIAL,
    snapshot_id BIGINT NOT NULL,
    side VARCHAR(4) NOT NULL,  -- 'bid' or 'ask'
    outcome VARCHAR(4) NOT NULL, -- 'yes' or 'no'
    level INTEGER NOT NULL,  -- 1-5
    price DECIMAL(10,8) NOT NULL,
    size DECIMAL(18,8) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, captured_at)
) PARTITION BY RANGE (captured_at);
```

### 4.2 Configuration Tables

```sql
-- Strategy definitions and settings
CREATE TABLE strategies (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    version VARCHAR(32) NOT NULL,
    enabled BOOLEAN DEFAULT false,
    config JSONB NOT NULL,  -- Full strategy configuration
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategy performance tracking
CREATE TABLE strategy_performance (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(64) REFERENCES strategies(strategy_id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    trades INTEGER DEFAULT 0,
    gross_pnl DECIMAL(18,4) DEFAULT 0,
    net_pnl DECIMAL(18,4) DEFAULT 0,
    sharpe_ratio DECIMAL(8,4),
    max_drawdown_pct DECIMAL(8,4),
    win_rate DECIMAL(5,4),
    UNIQUE(strategy_id, period_start)
);
```

### 4.3 Trading Tables

```sql
-- Enhanced decisions with strategy attribution
CREATE TABLE decisions (
    id SERIAL PRIMARY KEY,
    market_id_fk INTEGER REFERENCES markets(id),
    strategy_id VARCHAR(64) REFERENCES strategies(strategy_id),
    side VARCHAR(8) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL,
    model_probability DECIMAL(5,4) NOT NULL,
    market_implied_probability DECIMAL(5,4) NOT NULL,
    edge_bps INTEGER NOT NULL,
    stake_usd DECIMAL(18,4) NOT NULL,
    status VARCHAR(32) DEFAULT 'proposed',
    explanation TEXT NOT NULL,
    risk_flags TEXT DEFAULT '',
    features_used JSONB,  -- Snapshot of feature values
    strategy_version VARCHAR(32),
    requires_approval BOOLEAN DEFAULT true,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enhanced orders with full lifecycle
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    decision_id INTEGER REFERENCES decisions(id),
    client_order_id VARCHAR(128) UNIQUE NOT NULL,
    venue_order_id VARCHAR(128),
    mode VARCHAR(16) NOT NULL,  -- 'paper' or 'live'
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(16) DEFAULT 'limit',  -- limit, ioc, post_only
    price DECIMAL(10,8) NOT NULL,
    size DECIMAL(18,8) NOT NULL,
    filled_size DECIMAL(18,8) DEFAULT 0,
    avg_fill_price DECIMAL(10,8),
    notional_usd DECIMAL(18,4) NOT NULL,
    status VARCHAR(32) DEFAULT 'created',
    status_history JSONB DEFAULT '[]',  -- Array of {status, timestamp, metadata}
    retry_count INTEGER DEFAULT 0,
    submitted_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    filled_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    last_poll_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Position tracking with PnL
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    event_key VARCHAR(256) NOT NULL,
    market_id VARCHAR(128) NOT NULL,
    strategy_id VARCHAR(64),
    side VARCHAR(8) NOT NULL,
    entry_price DECIMAL(10,8) NOT NULL,
    current_price DECIMAL(10,8),
    quantity DECIMAL(18,8) NOT NULL,
    notional_usd DECIMAL(18,4) NOT NULL,
    unrealized_pnl DECIMAL(18,4) DEFAULT 0,
    realized_pnl DECIMAL(18,4) DEFAULT 0,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    is_open BOOLEAN DEFAULT true,
    close_reason VARCHAR(32)  -- 'exit_signal', 'stop_loss', 'expiration', 'manual'
);

-- Junction table: positions can have multiple orders (scaling in/out)
CREATE TABLE position_orders (
    position_id INTEGER REFERENCES positions(id),
    order_id INTEGER REFERENCES orders(id),
    quantity DECIMAL(18,8) NOT NULL,  -- How much of this order applies to position
    PRIMARY KEY (position_id, order_id)
);
```

---

## 5. Risk Management

### 5.1 Risk Engine Architecture

```python
class RiskEngine:
    """Multi-layer risk control system"""

    def evaluate(self, context: RiskContext) -> RiskDecision:
        # Layer 1: Global kill switches (fastest)
        if self.global_kill_switch.is_triggered:
            return RiskDecision.reject("global_kill_switch_active")

        # Layer 2: Market quality filters
        if not self._passes_market_quality(context.market):
            return RiskDecision.reject("market_quality")

        # Layer 3: Strategy-level limits
        if not self._passes_strategy_limits(context):
            return RiskDecision.reject("strategy_limit")

        # Layer 4: Portfolio-level constraints
        if not self._passes_portfolio_limits(context):
            return RiskDecision.reject("portfolio_limit")

        # Layer 5: Position sizing
        size = self._calculate_position_size(context)

        return RiskDecision.approve(size)
```

### 5.2 Risk Limits Configuration

```yaml
risk_limits:
  global:
    max_portfolio_drawdown_pct: 20
    max_daily_loss_usd: 500
    max_data_latency_minutes: 15
    max_execution_failure_rate: 0.20

  portfolio:
    max_correlated_exposure_pct: 30  # Same event cluster
    max_concentration_single_market_pct: 15
    max_positions_open: 10
    max_daily_var_pct: 10  # 95% 1-day VaR

  strategy:
    liquidity_momentum:
      max_position_pct: 10
      max_drawdown_pct: 10
      min_backtest_sharpe: 1.0
      max_daily_trades: 5

    event_catalyst:
      max_position_pct: 15
      max_drawdown_pct: 15
      min_days_to_resolution: 3
      max_days_to_resolution: 30

    mean_reversion:
      max_position_pct: 8
      max_drawdown_pct: 10
      min_z_score: 2.0

  market_quality:
    min_liquidity_usd: 5000
    max_spread_bps: 300
    min_volume_24h_usd: 1000
    max_price_volatility_1h_pct: 15
    blacklist_markets: []  # Populated dynamically
```

### 5.3 Circuit Breakers

| Trigger | Threshold | Action | Auto-Reset |
|---------|-----------|--------|------------|
| Portfolio DD | -20% | Kill all trading | Manual only |
| Strategy DD | -10% | Disable strategy | After 24h + review |
| Data Stale | >15 min | Pause new orders | When fresh |
| Exec Failures | >20% in 1h | Pause + alert | Manual only |
| Position Drift | >5% vs expected | Alert + reconcile | N/A |
| Daily Loss | >$500 | Kill for day | Next UTC day |

---

## 6. Execution Model

### 6.1 Polymarket CTF Integration

Polymarket uses the Conditional Tokens Framework (CTF) on Polygon:

```python
class PolymarketExecutionProvider:
    """Real execution via Polymarket CTF"""

    def submit_order(self, order: Order) -> OrderResult:
        # 1. Build CTF order structure
        ctf_order = self._build_ctf_order(order)

        # 2. Sign with wallet (from AWS Secrets Manager)
        signed_tx = self._sign_transaction(ctf_order)

        # 3. Submit to Polygon RPC
        tx_hash = self._submit_to_rpc(signed_tx)

        # 4. Update order state
        order.venue_order_id = tx_hash
        order.status = 'submitted'

        return OrderResult(success=True, tx_hash=tx_hash)

    def check_fill(self, order: Order) -> FillStatus:
        # Query CTF contract for order status
        # Return filled amount and average price
        pass
```

### 6.2 Slippage Model

```python
class SlippageModel:
    """Estimate execution slippage based on order book"""

    def estimate_slippage(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        order_book: OrderBook
    ) -> SlippageEstimate:
        # Walk the order book to find average fill price
        remaining = size_usd
        total_cost = 0  # Total dollars spent
        total_shares = 0  # Total shares received
        levels_consumed = 0

        for level in order_book.get_levels(side):
            if remaining <= 0:
                break
            # How much can we fill at this level (in dollars)
            available_at_level = level.size * level.price
            fill_at_level = min(remaining, available_at_level)
            # Quantity of shares we get at this level
            shares_at_level = fill_at_level / level.price
            total_shares += shares_at_level
            total_cost += fill_at_level
            remaining -= fill_at_level
            levels_consumed += 1

        if remaining > 0 or total_shares <= 0:
            return SlippageEstimate(
                can_fill=False,
                reason="insufficient_liquidity"
            )

        avg_price = total_cost / total_shares
        slippage_pct = (avg_price - order_book.mid_price) / order_book.mid_price

        return SlippageEstimate(
            can_fill=True,
            avg_fill_price=avg_price,
            slippage_pct=slippage_pct,
            levels_consumed=levels_consumed
        )
```

### 6.3 Reconciliation

```python
class ReconciliationService:
    """Reconcile system state with Polymarket"""

    def reconcile(self) -> ReconciliationReport:
        # Get positions from Polymarket API
        api_positions = self.polymarket.get_positions()

        # Get positions from blockchain (source of truth)
        chain_positions = self.ctf_contract.get_positions()

        # Get positions from internal system
        db_positions = self.db.get_open_positions()

        # Compare and identify drift
        drift = self._identify_drift(api_positions, chain_positions, db_positions)

        if drift.has_significant_discrepancy:
            self.alert_service.send_critical("Position drift detected", drift)
            self.kill_switch.trigger("position_drift")

        return ReconciliationReport(drift=drift, timestamp=now())
```

---

## 7. Monitoring & Observability

### 7.1 Metrics (CloudWatch)

| Metric | Namespace | Dimensions | Alarm |
|--------|-----------|------------|-------|
| `signal_generation_latency` | PolyClaw/Strategy | strategy_id | >30s |
| `order_submission_latency` | PolyClaw/Execution | mode | >5s |
| `data_freshness_seconds` | PolyClaw/Ingestion | market_id | >900s |
| `unrealized_pnl` | PolyClaw/Portfolio | strategy_id | < -$500 |
| `strategy_sharpe_7d` | PolyClaw/Performance | strategy_id | < 0.5 |
| `reconciliation_error_pct` | PolyClaw/Operations | - | >1% |
| `order_fill_rate` | PolyClaw/Execution | strategy_id | < 80% |

### 7.2 Logging

Structured JSON logs with correlation IDs:

```json
{
  "timestamp": "2026-03-22T14:30:00Z",
  "level": "INFO",
  "service": "strategy-engine",
  "correlation_id": "uuid-1234",
  "event": "signal_generated",
  "data": {
    "strategy_id": "liquidity_momentum",
    "strategy_version": "1.2.0",
    "market_id": "0xabc...",
    "signal": "buy_yes",
    "confidence": 0.72,
    "features": {
      "volume_surge_ratio": 2.3,
      "price_momentum_24h": 0.15,
      "liquidity_depth_usd": 15000
    },
    "market_snapshot": {
      "yes_price": 0.45,
      "spread_bps": 120,
      "liquidity_usd": 25000
    }
  }
}
```

### 7.3 Alert Routing

```yaml
alert_rules:
  - name: portfolio_drawdown_critical
    condition: unrealized_pnl < -500
    severity: critical
    channels:
      - telegram: "@polyclaw_alerts"
      - pagerduty: "polyclaw-production"
    action: kill_switch.enable("portfolio_drawdown")

  - name: data_stale_warning
    condition: max(data_age) > 10_minutes
    severity: warning
    channels:
      - telegram: "@polyclaw_alerts"
    action: none  # Auto-resolves when fresh

  - name: strategy_underperformance
    condition: strategy_sharpe_7d < 0.5 AND backtest_sharpe > 1.0
    severity: warning
    channels:
      - email: "ops@example.com"
    action: strategy.disable(strategy_id)
```

---

## 8. Deployment Phases

### Phase 1: Foundation (Weeks 1-4)

**Week 1: Data Infrastructure**
- [ ] Provision RDS Postgres (db.r6g.large)
- [ ] Create S3 bucket with lifecycle policies
- [ ] Implement historical backfill (90 days)
- [ ] Deploy Lambda ingestion function (3-min schedule)
- [ ] Migrate SQLite → Postgres

**Week 2: Multi-Strategy Framework**
- [ ] Create `BaseStrategy` interface
- [ ] Implement StrategyRegistry
- [ ] Port existing heuristic to `EventCatalyst` strategy
- [ ] Implement `LiquidityMomentum` strategy
- [ ] Build feature computation pipeline

**Week 3: Backtesting Engine**
- [ ] Implement `BacktestRunner` with event-driven simulation
- [ ] Build slippage model from order book data
- [ ] Run walk-forward validation (60-day train, 30-day test)
- [ ] Generate performance reports for each strategy

**Week 4: Portfolio Risk**
- [ ] Implement `PortfolioRiskEngine`
- [ ] Build correlation tracking by event cluster
- [ ] Implement Kelly position sizing
- [ ] Add circuit breakers (global + strategy-level)

**Phase 1 Gate:** Backtest Sharpe >1.2, max DD <15% for ≥2 strategies

### Phase 2: Execution (Weeks 5-8)

**Week 5: Polymarket Integration**
- [ ] Implement `PolymarketCTFProvider`
- [ ] Set up AWS Secrets Manager for private keys
- [ ] Build order state machine
- [ ] Implement idempotent order submission

**Week 6: Order Management**
- [ ] Add limit order types (post-only, IOC)
- [ ] Implement price bands (2% fat finger protection)
- [ ] Build retry logic with exponential backoff
- [ ] Add order tracking dashboard

**Week 7: Reconciliation**
- [ ] Implement reconciliation service
- [ ] Build discrepancy detection
- [ ] Add auto-close on significant drift
- [ ] Create position drift alerts

**Week 8: Shadow Mode (Part 1)**
- [ ] Deploy full stack with paper execution
- [ ] Run shadow trading for 1 week
- [ ] Track signal accuracy vs market outcomes
- [ ] Tune confidence thresholds

**Week 9: Shadow Mode (Part 2) + Staged Live**
- [ ] Complete 2nd week of shadow trading
- [ ] Finalize signal accuracy validation
- [ ] Enable live trading at 10% size ($5 positions)
- [ ] Whitelist 5-10 high-liquidity markets

**Phase 2/3 Gate:** 100+ paper trades, <1% reconciliation error, signal accuracy >60%, first live trade executed

### Phase 3: Production (Weeks 10-13)

**Week 10: Observability**
- [ ] Deploy Grafana dashboards
- [ ] Configure CloudWatch alarms
- [ ] Set up Telegram/PagerDuty integration
- [ ] Build PnL attribution reports
- [ ] Human review of every trade (first 3 days of live)

**Week 11: Scaling**
- [ ] If profitable: scale to 25% → 50% → 100%
- [ ] Expand market whitelist (liquidity >$50K)
- [ ] Monitor slippage vs size
- [ ] Optimize for fees

**Week 13: Hardening**
- [ ] Implement CI/CD (GitHub Actions → ECR → ECS)
- [ ] Set up Alembic migrations
- [ ] Test disaster recovery (restore from backup)
- [ ] Document runbooks

**Phase 3 Gate:** Live trading profitable for 2+ weeks, 99.5% uptime, DR tested

---

## 9. Security Considerations

### 9.1 Wallet Security

- **Storage:** Private keys in AWS Secrets Manager (encrypted with KMS)
- **Derivation:** Use HD wallet (BIP-32) with separate keys per strategy
- **Limits:** Set Polymarket sub-account limits (emergency circuit)
- **Monitoring:** Alert on any unexpected withdrawals

### 9.2 Infrastructure Security

- **Network:** ECS tasks in private subnets, no public IPs
- **Access:** IAM roles for service-to-service auth, no long-term credentials
- **Encryption:** TLS 1.3 for all external connections, AES-256 at rest
- **Audit:** CloudTrail for all AWS API calls

### 9.3 Operational Security

- **Deployment:** Require MFA for production deployments
- **Secrets:** Rotate Polymarket keys monthly
- **Monitoring:** Alert on any access to Secrets Manager
- **Incident:** Documented procedure for key compromise

---

## 10. Disaster Recovery

### 10.1 RPO/RTO Targets

| Data Type | RPO | RTO | Method |
|-----------|-----|-----|--------|
| Trade records | 0 | 1 hour | Synchronous replication |
| Market data | 4 hours | 2 hours | S3 + RDS snapshots |
| Configuration | 1 hour | 30 min | Git + S3 backup |
| System state | 1 hour | 2 hours | ECS redeploy |

### 10.2 Backup Strategy

- **RDS:** Automated daily snapshots, 35-day retention
- **S3:** Versioning enabled, cross-region replication to us-west-2
- **Config:** Terraform state in S3 with DynamoDB locking

### 10.3 Recovery Procedures

```
RDS Failure:
1. Detect via CloudWatch alarm
2. Promote read replica (automated)
3. Update ECS task config
4. Verify data consistency
5. Root cause analysis

ECS Failure:
1. Service auto-restarts tasks
2. If persistent, rollback to last image
3. Verify system state reconciliation
4. Manual intervention if needed

Key Compromise:
1. Kill switch immediate
2. Rotate keys via Secrets Manager
3. Update ECS tasks
4. Audit all transactions since compromise
```

---

## 11. Success Metrics

### 11.1 Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Uptime | 99.5% | CloudWatch |
| Data latency | <5 min | Ingestion timestamps |
| Order latency | <5 sec | Submission timestamps |
| Reconciliation accuracy | 99.9% | Daily reconciliation reports |
| Recovery time | <4 hours | DR test results |

### 11.2 Trading Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Portfolio Sharpe | >1.0 | Daily PnL |
| Max drawdown | <20% | Peak-to-trough |
| Win rate | >50% | Closed positions |
| Signal accuracy | >60% | Shadow + live combined |
| Slippage impact | <0.5% | Expected vs actual fill |

### 11.3 Operational Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| False positive alerts | <5/week | Alert history |
| Mean time to alert response | <15 min (critical) | PagerDuty |
| Deployment frequency | 1/week | GitHub Actions |
| Change failure rate | <10% | Incidents per deploy |

---

## 12. Open Questions & Risks

### 12.1 Technical Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Polymarket API changes | High | Abstract provider interface, rapid response team |
| Polygon network congestion | Medium | Priority gas fees, order timeout handling |
| Data quality issues | High | Multiple data sources, anomaly detection |
| Strategy overfit | High | Walk-forward validation, minimum sample sizes |

### 12.2 Business Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Regulatory changes | Medium | Stay informed, maintain compliance docs |
| Market regime shift | High | Multi-strategy, kill switches, position limits |
| Capital constraints | Low | Staged deployment, performance-based scaling |

### 12.3 Open Questions

1. **Slippage Model:** How accurate is the order book-based slippage estimate vs reality?
2. **Correlation:** How do we define and track event clusters for correlation limits?
3. **Capacity:** At what AUM do we hit meaningful slippage on target markets?
4. **Rebalance:** How frequently should we rebalance between strategies?

---

## 13. Appendix

### 13.1 Glossary

- **CTF:** Conditional Tokens Framework (Polymarket's on-chain settlement)
- **RPO:** Recovery Point Objective (max acceptable data loss)
- **RTO:** Recovery Time Objective (max acceptable downtime)
- **VaR:** Value at Risk (potential loss at confidence level)
- **Walk-forward:** Backtesting method that simulates real-time retraining

### 13.2 References

- Polymarket Gamma API Documentation
- CTF Smart Contract Specification
- AWS ECS Fargate Best Practices
- PostgreSQL Partitioning Guide

---

## Approval

| Role | Name | Date | Approved |
|------|------|------|----------|
| Author | Claude Code | 2026-03-22 | ✓ |
| Review | TBD | | |
| Approval | TBD | | |
