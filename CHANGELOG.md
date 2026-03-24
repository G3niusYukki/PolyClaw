# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive documentation overhaul (README, LICENSE, CONTRIBUTING)

## [0.1.0] - 2026-03-23

### Added

#### Core Features
- **Multi-Strategy Framework** — Pluggable strategy architecture with `BaseStrategy` interface and `StrategyRegistry`
- **EventCatalyst Strategy** — High-conviction event detection near resolution (3-30 days)
- **LiquidityMomentum Strategy** — Volume spike and price breakout detection
- **FeatureEngine** — TTL-cached technical indicators for strategy features

#### Risk Management
- **RiskEngine** — Market-level risk validation (spread, liquidity, data freshness)
- **PortfolioRiskEngine** — Portfolio-level risk controls (concentration, correlation)
- **KellyPositionSizer** — Mathematical optimal position sizing with fractional Kelly
- **EventClusterTracker** — Event correlation tracking for exposure management

#### Execution
- **OrderStateMachine** — Complete order lifecycle management
- **PriceBandValidator** — 2% price deviation protection
- **RetryExecutor** — Exponential backoff with idempotent submissions
- **OrderTracker** — Real-time order status tracking
- **StagedPositionSizer** — Gradual capital deployment (shadow → 10% → 25% → 50% → 100%)
- **MarketWhitelist** — Default-deny market approval system

#### CTF Integration
- **PolymarketCTFProvider** — Direct blockchain integration with confirmed ABI selectors
  - `createOrder=0x6f652e1a`
  - `cancelOrder=0x0fdb031d`
- **LiveTradingPrerequisites** — Startup validation (RPC, selectors, contracts, balances)
- **On-Chain Position Queries** — Real-time balance verification via `eth_call`
- **EIP-1559 Transaction Support** — Modern Ethereum transaction format

#### Safety Systems
- **GlobalCircuitBreaker** — Portfolio-level protection (DD >20%, daily loss >$500)
- **StrategyCircuitBreaker** — Per-strategy protection with auto-reset
- **CTFLiveCircuitBreaker** — Transaction-level protection
- **KillSwitch** — Emergency stop for all trading
- **ShadowMode** — Signal validation against real market outcomes

#### Data Infrastructure
- **MarketFetcher** — Polymarket Gamma API integration
- **OrderBookFetcher** — Best bid/ask retrieval
- **TradeFetcher** — Historical trade data ingestion
- **BackfillRunner** — Historical data backfilling
- **Lambda Ingestion** — AWS Lambda + EventBridge scheduled pipeline (3-minute intervals)

#### Backtesting
- **BacktestRunner** — Complete backtesting engine
- **SlippageModel** — Realistic slippage simulation
- **WalkForwardValidator** — Out-of-sample validation
- **PerformanceReport** — Comprehensive performance metrics

#### API & Services
- **FastAPI Application** — RESTful API with automatic documentation
- **AnalysisService** — Market scanning and decision orchestration
- **RunnerService** — Complete tick cycle management
- **ExecutionService** — Order approval and dispatch
- **ProposalWorkflowService** — Proposal persistence and status management

#### Observability
- **MetricsCollector** — CloudWatch metrics emission
- **AlertRouter** — Telegram/PagerDuty alerting with severity routing
- **PnLReporter** — Profit/loss attribution reporting
- **DailyReportGenerator** — Automated daily summaries
- **AnomalyDetector** — 3-sigma statistical alerting
- **HealthChecker** — Component health monitoring
- **Grafana Dashboards** — 8-panel monitoring (system health, PnL, Sharpe, fill rate, latency, reconciliation)
- **CloudWatch Alarms** — 6 metrics with SNS routing

#### Reconciliation
- **ReconciliationService** — Position verification across systems
- **DiscrepancyDetector** — Drift identification
- **DriftAlerts** — Automated drift notifications

#### Scaling & Expansion
- **ScalingManager** — Automated stage advancement
- **PerformanceEvaluator** — Performance criteria assessment
- **MarketExpander** — Auto-candidate detection
- **SlippageMonitor** — Excessive slippage detection
- **FeeCalculator** — Platform fee and gas estimation

#### Disaster Recovery
- **DisasterRecoveryManager** — DR orchestration
- **Cross-Region S3 Replication** — Data redundancy
- **RDS Read Replica** — Database failover capability

#### Infrastructure (Terraform)
- **ECS Fargate** — Serverless container orchestration (4 microservices)
- **RDS PostgreSQL** — Managed database (db.t4g.medium)
- **Application Load Balancer** — Path-based routing
- **S3 Buckets** — Data, logs, and CloudTrail storage
- **Secrets Manager** — Secure credential storage
- **IAM Roles** — Least-privilege access control
- **VPC Networking** — Private/public subnet isolation

#### CI/CD
- **GitHub Actions CI** — Lint (ruff), type-check (mypy), test (pytest ≥80% coverage), migration validation
- **GitHub Actions CD** — Docker build, ECR push, ECS deployment
- **Multi-Environment** — Staging (main branch) and Production (releases)

#### Testing
- **400+ Tests** — Comprehensive test coverage
- **Live Smoke Tests** — Full pipeline validation (manual trigger)
- **Unit Tests** — Component-level testing
- **Integration Tests** — System interaction testing

### Security
- Default paper trading mode
- Manual approval gates
- Multi-layer circuit breakers
- Price band validation
- Market whitelisting
- Comprehensive audit logging

### Documentation
- `CLAUDE.md` — Development guide and architecture details
- `SAFETY_CHECKLIST.md` — Pre-live safety verification
- `docs/runbook.md` — Operational procedures
- `docs/dr-test-procedure.md` — Disaster recovery testing

---

## Release History

| Version | Date | Status |
|---------|------|--------|
| 0.1.0 | 2026-03-23 | ✅ Initial Release |

---

## Future Roadmap

### Planned Features

- [ ] Additional trading strategies (MeanReversion, Arbitrage)
- [ ] Machine learning model integration
- [ ] WebSocket real-time data feeds
- [ ] Mobile app for monitoring
- [ ] Multi-exchange support
- [ ] Advanced portfolio optimization
- [ ] Social trading features
- [ ] Strategy marketplace

### Infrastructure Improvements

- [ ] Kubernetes deployment option
- [ ] GraphQL API
- [ ] Enhanced caching layer (Redis)
- [ ] Multi-region active-active setup
- [ ] Enhanced monitoring (Prometheus + Grafana)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting changes.

---

**Note**: This changelog follows [Keep a Changelog](https://keepachangelog.com/) format. 
Version numbers follow [Semantic Versioning](https://semver.org/).
