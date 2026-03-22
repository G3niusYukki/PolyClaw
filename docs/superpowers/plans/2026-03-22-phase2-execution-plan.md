# Phase 2: Execution — Implementation Plan

**Date:** 2026-03-22
**Branch:** `feat/phase2-execution`
**Worktree:** `.worktrees/phase2-execution/`
**Source:** `docs/superpowers/specs/2026-03-22-production-roadmap-design.md`

---

## Phase 2 Gate Criteria

100+ paper trades, <1% reconciliation error, signal accuracy >60%, first live trade executed

---

## Week 5: Polymarket Integration

### 5.1 PolymarketCTFProvider
- [ ] Create `polyclaw/providers/ctf.py` with `PolymarketCTFProvider` implementing `ExecutionProvider` protocol
  - Connect to Polymarket CTF (Conditional Tokens Framework) on Polygon
  - `submit_order(order: Order) -> OrderResult`: build CTF order, sign with wallet, submit to Polygon RPC
  - `check_fill(order: Order) -> FillStatus`: query CTF contract for order status
  - `get_positions() -> list[Position]`: fetch current positions from CTF
  - `get_balances() -> dict`: fetch USDC/ETH balances
- [ ] Create `polyclaw/providers/signer.py` with wallet signing utilities
  - Support for signing CTF transactions
  - Key format handling (private key hex)
- [ ] Update `polyclaw/providers/paper_execution.py` to match updated `ExecutionProvider` interface

### 5.2 AWS Secrets Manager Integration
- [ ] Create `polyclaw/secrets.py` with `SecretsManager` client
  - `get_private_key() -> str`: retrieve CTF wallet private key from AWS Secrets Manager
  - `get_api_keys() -> dict`: retrieve Polymarket API keys
  - Fallback to env vars for local development
- [ ] Update `infrastructure/secrets.tf` with Secrets Manager resources:
  - `polyclaw/ctf/private_key`
  - `polyclaw/polymarket/api_key`
  - `polyclaw/telegram/bot_token`
- [ ] Add `secrets_manager/` to `.env.example`

### 5.3 Order State Machine
- [ ] Enhance `polyclaw/models.py` Order model with full state machine
  - States: CREATED → SUBMITTED → ACKNOWLEDGED → PARTIAL_FILL → FILLED | CANCELING → CANCELED
  - `status_history` JSONB field tracking all transitions with timestamps and metadata
  - `venue_order_id` field for CTF transaction hash
  - `client_order_id` for idempotency
- [ ] Create `polyclaw/execution/state.py` with `OrderStateMachine` class
  - `transition(order, new_state, metadata)` method
  - Valid state transitions enforcement
  - Emit events on transitions

### 5.4 Idempotent Order Submission
- [ ] Implement idempotency key pattern in `PolymarketCTFProvider`
  - Use `client_order_id` as idempotency key
  - Store submitted orders in DB with idempotency key
  - Check for existing order before submitting
  - Return cached result if order already submitted with same key

### 5.5 Verification
- [ ] Run `pytest` — all tests must pass
- [ ] `PolymarketCTFProvider` can be instantiated (won't fail on import)
- [ ] Order state machine enforces valid transitions
- [ ] Idempotent submission returns cached result for duplicate keys

---

## Week 6: Order Management

### 6.1 Limit Order Types
- [ ] Create `polyclaw/execution/orders.py` with `OrderType` enum and `OrderSpec` dataclass
  - `OrderType`: LIMIT, IOC (Immediate-Or-Cancel), POST_ONLY, MARKET
  - `OrderSpec`: type, side, price, size, market_id, outcome
- [ ] Update `PolymarketCTFProvider.submit_order()` to handle all order types
  - LIMIT: submit at specified price
  - IOC: submit with immediate cancel if not filled
  - POST_ONLY: ensure order posts to book without taking liquidity
  - MARKET: submit at best available price

### 6.2 Price Bands (Fat Finger Protection)
- [ ] Create `polyclaw/execution/price_bands.py` with `PriceBandValidator` class
  - `validate(order_spec: OrderSpec, reference_price: float) -> tuple[bool, str]`
  - Configurable band (default 2%): reject if order price > reference * (1 + band) or < reference * (1 - band)
  - Log rejections with reason
- [ ] Integrate into `ExecutionService` before order submission

### 6.3 Retry Logic with Exponential Backoff
- [ ] Create `polyclaw/execution/retry.py` with `RetryExecutor` class
  - Decorator `@retry(max_attempts=3, base_delay=1.0, max_delay=30.0, exponential_base=2.0)`
  - Retryable exceptions: network errors, RPC timeouts, rate limit errors
  - Non-retryable: invalid order, insufficient balance, market closed
  - Log each retry attempt
  - Track `retry_count` on order record

### 6.4 Order Tracking
- [ ] Create `polyclaw/execution/tracker.py` with `OrderTracker` class
  - `poll_order(order: Order) -> OrderUpdate`: check order status from CTF
  - `poll_loop(order: Order, interval: int = 5, timeout: int = 60)`: poll until filled/timeout
  - Background polling mechanism for open orders
  - Update order status in DB on each poll
- [ ] Add `/orders/{id}` and `/orders` API endpoints to `api/main.py`
- [ ] Add `GET /positions` endpoint enhancement to show real-time positions

### 6.5 Verification
- [ ] Run `pytest` — all tests must pass
- [ ] Price band rejects orders outside 2% of reference price
- [ ] Retry logic respects exponential backoff
- [ ] Order tracker updates order status correctly

---

## Week 7: Reconciliation

### 7.1 Reconciliation Service
- [ ] Create `polyclaw/reconciliation/__init__.py`
- [ ] Create `polyclaw/reconciliation/service.py` with `ReconciliationService` class
  - `reconcile() -> ReconciliationReport`: compare system state vs Polymarket vs blockchain
  - `get_system_positions(session) -> dict`: positions from internal DB
  - `get_api_positions() -> dict`: positions from Polymarket API
  - `get_chain_positions() -> dict`: positions from CTF contract
  - `ReconciliationReport`: drift_detected, drift_amount, discrepancy_items, timestamp
- [ ] `discrepancy_items` lists specific mismatches: market_id, expected_qty, actual_qty, source

### 7.2 Discrepancy Detection
- [ ] Create `polyclaw/reconciliation/detector.py` with `DiscrepancyDetector` class
  - Compare positions across all three sources (DB, API, chain)
  - Identify drift with tolerance threshold (default 0.01 USD)
  - Categorize drift: MISSING_ON_CHAIN, EXTRA_ON_CHAIN, QUANTITY_MISMATCH, PRICE_MISMATCH
  - `DetectionResult`: discrepancies (list), total_drift_usd, is_critical (bool)

### 7.3 Auto-Close on Drift
- [ ] Integrate auto-close into `ReconciliationService`
  - If `total_drift_usd > auto_close_threshold` (default $10): trigger auto-close workflow
  - Close drifting positions by submitting offsetting orders
  - Log all auto-close actions
  - Send alert via notifications

### 7.4 Position Drift Alerts
- [ ] Create `polyclaw/reconciliation/alerts.py` with `DriftAlerts` class
  - `send_drift_alert(report: ReconciliationReport)`
  - Log critical drift to audit log
  - Call notification service for critical alerts
  - Severity levels: WARNING (drift < $5), CRITICAL (drift >= $5)
- [ ] Add `/reconciliation/run` and `/reconciliation/report` API endpoints

### 7.5 Verification
- [ ] Run `pytest` — all tests must pass
- [ ] Reconciliation correctly identifies position drift between sources
- [ ] Auto-close triggers when drift exceeds threshold
- [ ] Drift alerts sent to audit log

---

## Week 8: Shadow Mode (Part 1)

### 8.1 Shadow Mode Infrastructure
- [ ] Create `polyclaw/shadow/__init__.py`
- [ ] Create `polyclaw/shadow/mode.py` with `ShadowModeEngine` class
  - `process_shadow_signals(signals: list[Signal], market_data: dict)`
  - Simulate order execution without actual submission
  - Track "shadow positions" in memory and DB
  - Calculate shadow PnL based on market outcomes
- [ ] Create `polyclaw/shadow/tracker.py` with `ShadowTracker` class
  - Track simulated fills: shadow_filled_price, shadow_fill_time, shadow_quantity
  - Compare shadow fills against actual market prices at resolution
  - `ShadowResult`: market_id, signal, shadow_fill, actual_outcome, pnl, accuracy

### 8.2 Signal Accuracy Monitoring
- [ ] Create `polyclaw/shadow/accuracy.py` with `SignalAccuracyMonitor` class
  - Track correct/incorrect predictions over time
  - `update(market_id: str, predicted_side: str, actual_outcome: str)`
  - `get_accuracy(window_days: int = 30) -> dict`: accuracy, total_signals, correct_signals
  - Rolling accuracy with confidence interval
  - Break down by strategy: accuracy per strategy_id

### 8.3 Shadow Mode API
- [ ] Add shadow mode endpoints to `api/main.py`:
  - `GET /shadow/results` — list shadow trading results
  - `GET /shadow/accuracy` — signal accuracy report
  - `POST /shadow/reset` — reset shadow positions
  - `GET /shadow/positions` — current shadow positions
- [ ] Shadow mode toggle: `SHADOW_MODE_ENABLED=true|false` env var

### 8.4 Deployment Configuration
- [ ] Create `infrastructure/ecs.tf` with ECS Fargate task definitions:
  - Ingestion service task definition
  - Strategy engine task definition
  - Execution service task definition
  - Monitor service task definition
- [ ] Create `infrastructure/alb.tf` with Application Load Balancer
- [ ] Create `infrastructure/ecs-task-iam.tf` with task execution roles

### 8.5 Verification
- [ ] Run `pytest` — all tests must pass
- [ ] Shadow mode correctly simulates orders without submission
- [ ] Signal accuracy monitor correctly tracks predictions vs outcomes

---

## Week 9: Shadow Mode (Part 2) + Staged Live

### 9.1 Staged Position Sizing
- [ ] Create `polyclaw/execution/staged_size.py` with `StagedPositionSizer` class
  - `get_stage() -> int`: current stage (0=shadow, 1=10%, 2=25%, 3=50%, 4=100%)
  - `scale_stake(base_stake: float) -> float`: apply stage scaling
  - Stage transitions based on: shadow accuracy >60%, paper trades >50, no critical drift
  - Manual override capability
  - Config: `STAGE_SIZE_PCT` mapping in `RISK_CONFIG.yaml`

### 9.2 Market Whitelist
- [ ] Create `polyclaw/execution/whitelist.py` with `MarketWhitelist` class
  - `is_allowed(market_id: str) -> bool`: check if market is whitelisted for live trading
  - `get_min_liquidity_threshold() -> float`: minimum liquidity for whitelist
  - Default whitelist: 5-10 high-liquidity markets (manual configuration)
  - Expand whitelist criteria: liquidity >$50K, spread <200 bps, volume >$10K
  - Store whitelist in DB or config file

### 9.3 Confidence Threshold Tuning
- [ ] Create `polyclaw/shadow/tuning.py` with `ThresholdTuner` class
  - `suggest_threshold(strategy_id: str, target_accuracy: float = 0.60) -> float`
  - Analyze historical shadow results to find optimal confidence threshold
  - Binary search on threshold to find minimum passing accuracy
  - Output: suggested_threshold, current_threshold, analysis_window

### 9.4 Shadow-to-Live Transition
- [ ] Create `polyclaw/shadow/transition.py` with `LiveTransitionManager` class
  - `can_go_live() -> tuple[bool, list[str]]`: check all gate criteria
  - Gates: accuracy >60%, paper_trades >100, reconciliation_error <1%, no_active_circuit_breakers
  - `trigger_live()`: enable live trading at current stage
  - `rollback()`: revert to shadow mode
  - All transitions logged to audit log

### 9.5 Verification
- [ ] Run `pytest` — all tests must pass
- [ ] Staged sizing correctly scales stake by stage
- [ ] Market whitelist blocks non-whitelisted markets
- [ ] Threshold tuner suggests reasonable thresholds
- [ ] Live transition manager correctly validates all gate criteria

---

## Final Verification
- [ ] All 5 weeks complete
- [ ] `pytest` — all tests pass
- [ ] Phase 2 gate criteria ready for validation
- [ ] PolymarketCTFProvider implemented and tested
- [ ] Shadow mode infrastructure operational
