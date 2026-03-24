<p align="center">
  <img src="https://img.shields.io/badge/PolyClaw-v0.1.0-blue?style=for-the-badge" alt="PolyClaw">
  <br>
  <strong>Guarded Polymarket Auto-Analysis & Execution Framework</strong>
  <br>
  <em>Algorithmic trading for prediction markets with multi-layer safety controls</em>
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/Features-Overview-green?style=flat-square" alt="Features"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick%20Start-Guide-orange?style=flat-square" alt="Quick Start"></a>
  <a href="#documentation"><img src="https://img.shields.io/badge/Docs-Complete-blue?style=flat-square" alt="Documentation"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License"></a>
</p>

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Live Trading Readiness](#live-trading-readiness)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Safety & Risk Management](#safety--risk-management)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [License](#license)

---

## Overview

**PolyClaw** is a production-ready algorithmic trading framework for [Polymarket](https://polymarket.com) — the world's largest prediction market platform. It combines multi-strategy analysis, comprehensive risk management, and blockchain-native execution to enable automated trading with institutional-grade safety controls.

> **Default Mode: Paper Trading**  
> Live execution is intentionally gated behind multiple layers of configuration, validation, and human oversight.

### Why PolyClaw?

- **Multi-Strategy Framework**: Dynamically load and combine trading strategies
- **Institutional Risk Controls**: Kelly position sizing, circuit breakers, and portfolio-level risk limits
- **Blockchain-Native**: Direct integration with Polymarket's CTF (Conditional Tokens Framework) on Polygon
- **Shadow Mode**: Validate strategies against real market outcomes before risking capital
- **Cloud-Native Architecture**: Terraform-managed AWS infrastructure with auto-scaling
- **Comprehensive Observability**: Real-time monitoring, alerting, and performance analytics

---

## Features

### Trading Strategies

- **EventCatalyst**: Identifies high-conviction events near resolution (3-30 days) with sentiment analysis
- **LiquidityMomentum**: Detects volume spikes and price breakouts for momentum trades
- **Strategy Registry**: Dynamically enable/disable strategies with hot-swapping support
- **Feature Engine**: TTL-cached technical indicators and market features

### Risk Management

- **Kelly Position Sizing**: Mathematical optimal position sizing with fractional Kelly adjustment
- **Portfolio Risk Engine**: Concentration limits, correlation tracking, exposure management
- **Multi-Level Circuit Breakers**:
  - Global: Portfolio-level protection (DD >20%, daily loss >$500)
  - Strategy: Per-strategy protection with auto-reset
  - CTF: Transaction-level protection
- **Price Band Validation**: Automatic rejection of orders with >2% price deviation

### Execution Engine

- **Order State Machine**: Full lifecycle management from creation to fill
- **Retry Logic**: Exponential backoff with idempotent order submission
- **Real-Time Reconciliation**: On-chain position verification via `eth_call`
- **Staged Position Sizing**: Gradual capital deployment (shadow → 10% → 25% → 50% → 100%)

### Infrastructure

- **AWS ECS Fargate**: Serverless container orchestration
- **RDS PostgreSQL**: Production database with read replicas
- **Lambda + EventBridge**: Scheduled market data ingestion (3-min intervals)
- **CloudWatch + Grafana**: Comprehensive monitoring and dashboards
- **Multi-Region DR**: Cross-region S3 replication and RDS failover

### Observability

- **PnL Attribution**: Strategy-level and market-level performance tracking
- **Anomaly Detection**: 3-sigma statistical alerts for PnL, volume, and spread anomalies
- **Alert Routing**: Telegram/PagerDuty with severity-based routing
- **Audit Logging**: Complete decision trail for compliance

---

## Live Trading Readiness

PolyClaw is at **readiness level 8.5/10** for live trading.

### Confirmed Capabilities

| Component | Status | Details |
|-----------|--------|---------|
| CTF ABI Selectors | ✅ Confirmed | `createOrder=0x6f652e1a`, `cancelOrder=0x0fdb031d` |
| On-Chain Position Queries | ✅ Active | Real-time balance verification via `eth_call` |
| Startup Validation | ✅ Implemented | `LiveTradingPrerequisites` checks RPC, selectors, balances |
| Reconciliation Gating | ✅ Active | Blocks trading when data sources unavailable |
| Smoke Tests | ✅ Available | Full pipeline tests with `-m live_manual` marker |
| Shadow Mode | ✅ Default | Validates signals before live capital deployment |

### Pre-Live Checklist

See [`SAFETY_CHECKLIST.md`](SAFETY_CHECKLIST.md) for comprehensive pre-live requirements.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Pipeline                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                 │
│   │ Polymarket│───▶│ Ingestion │───▶│ Analysis │                │
│   │   API    │    │ Pipeline  │    │  Engine  │                │
│   └──────────┘    └──────────┘    └────┬─────┘                │
│                                         │                      │
│                    ┌────────────────────┼────────────────┐     │
│                    ▼                    ▼                ▼     │
│              ┌──────────┐       ┌──────────┐      ┌──────────┐ │
│              │ Strategies│      │   Risk   │      │ Execution│ │
│              │  Engine   │      │  Engine  │      │  Engine  │ │
│              └────┬─────┘      └────┬─────┘      └────┬─────┘ │
│                   │                  │                 │      │
│                   └──────────────────┴─────────────────┘      │
│                                      │                        │
│                                      ▼                        │
│                              ┌──────────┐                    │
│                              │  CTF/Polygon  │                │
│                              │  Blockchain   │                │
│                              └──────────┘                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage & Observability                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│   │  PostgreSQL │  │    S3    │  │CloudWatch│  │  Grafana │      │
│   │  Database   │  │  Buckets │  │  Metrics │  │Dashboards│      │
│   └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Core Components

| Layer | Components | Purpose |
|-------|------------|---------|
| **Providers** | PolymarketGamma, CTF | Market data & execution |
| **Services** | Analysis, Runner, Execution | Business logic orchestration |
| **Strategies** | EventCatalyst, LiquidityMomentum | Trading signal generation |
| **Risk** | RiskEngine, PortfolioRisk, KellySizing | Multi-level risk controls |
| **Execution** | OrderStateMachine, RetryExecutor, Tracker | Order lifecycle management |
| **Monitoring** | MetricsCollector, AlertRouter, AnomalyDetector | Observability & alerting |

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16 (production) or SQLite (development)
- [Optional] AWS CLI (for deployment)
- [Optional] Terraform 1.5+ (for infrastructure)

### Installation

```bash
# Clone the repository
git clone https://github.com/G3niusYukki/PolyClaw.git
cd PolyClaw

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your settings
```

### Running Locally

```bash
# Start the API server (development mode)
uvicorn polyclaw.api.main:app --reload

# Run a full analysis cycle (CLI)
polyclaw tick

# Run backtest with walk-forward validation
polyclaw backtest --strategy event_catalyst
```

### Docker Compose

```bash
# Start full stack (app + PostgreSQL)
docker-compose up -d

# View logs
docker-compose logs -f polyclaw
```

---

## Documentation

### API Reference

Once running, access the interactive API documentation at:

```
http://localhost:8000/docs  # Swagger UI
http://localhost:8000/redoc # ReDoc
```

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/health/detailed` | GET | Component health status |
| `/scan` | POST | Run market analysis |
| `/candidates` | GET | Ranked market opportunities |
| `/decisions` | GET/POST | Trading decisions |
| `/execute-ready` | POST | Execute approved decisions |
| `/shadow/results` | GET | Shadow mode performance |
| `/reports/pnl` | GET | PnL reports |
| `/kill-switch` | GET/POST | Emergency stop control |

### Additional Documentation

- [`CLAUDE.md`](CLAUDE.md) — Development guide and architecture details
- [`SAFETY_CHECKLIST.md`](SAFETY_CHECKLIST.md) — Pre-live safety verification
- [`docs/runbook.md`](docs/runbook.md) — Operational procedures
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines

---

## Safety & Risk Management

### 9-Layer Safety Architecture

1. **Configuration Defaults**: All modes default to `paper` trading
2. **Startup Prerequisites**: Automatic validation of RPC, contracts, balances
3. **Approval Gate**: Manual approval required before any execution
4. **Kill Switch**: Emergency stop accessible via API
5. **Global Circuit Breaker**: Portfolio-level protection triggers
6. **Strategy Circuit Breaker**: Per-strategy protection with auto-reset
7. **Price Band Validator**: Rejects anomalous price orders
8. **Reconciliation Gating**: Blocks trading when data unavailable
9. **Market Whitelist**: Default-deny with explicit market approval

### Risk Configuration

See [`RISK_CONFIG.yaml`](RISK_CONFIG.yaml) for default thresholds:

```yaml
# Key Parameters (All Conservative by Default)
EXECUTION_MODE: paper
MAX_POSITION_USD: 50
MAX_TOTAL_EXPOSURE_USD: 250
MAX_DAILY_LOSS_USD: 200
MIN_CONFIDENCE: 0.62
MIN_EDGE_BPS: 700
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | SQLite | Database connection string |
| `EXECUTION_MODE` | `paper` | `paper` or `live` |
| `MARKET_SOURCE` | `sample` | `sample` or `polymarket` |
| `REQUIRE_APPROVAL` | `true` | Require manual approval |
| `LIVE_TRADING_ENABLED` | `false` | Enable live trading |
| `SHADOW_MODE_ENABLED` | `true` | Enable shadow validation |
| `CTF_CONTRACT_ADDRESS` | - | CTF contract on Polygon |
| `POLYGON_RPC_URL` | - | Polygon RPC endpoint |

See [`.env.example`](.env.example) for complete configuration.

---

## Development

### Testing

```bash
# Run all tests (excludes live tests)
pytest

# Run with coverage
pytest --cov=polyclaw --cov-report=term-missing

# Run live smoke tests (requires CTF_PRIVATE_KEY)
pytest -m live_manual

# Run specific test file
pytest polyclaw/tests/test_strategies.py -v
```

### Code Quality

```bash
# Linting
ruff check polyclaw/
ruff check --fix polyclaw/

# Type checking
mypy polyclaw/

# Format code
ruff format polyclaw/
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1
```

---

## Deployment

### AWS Infrastructure (Production)

```bash
cd infrastructure/

# Initialize Terraform
terraform init

# Plan changes
terraform plan

# Apply
terraform apply
```

### CI/CD Pipeline

GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`): Lint, type-check, test, migration validation
- **CD** (`.github/workflows/deploy.yml`): Docker build, ECR push, ECS deployment

Deployment triggers:
- Push to `main` → Deploy to Staging
- Release published → Deploy to Production

### Infrastructure Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Compute | ECS Fargate | Container orchestration |
| Database | RDS PostgreSQL | Primary data store |
| Storage | S3 | Market data, logs, backups |
| Ingestion | Lambda + EventBridge | Scheduled data pipeline |
| Load Balancer | ALB | Traffic routing |
| Monitoring | CloudWatch + Grafana | Metrics and dashboards |
| Secrets | Secrets Manager | API keys, private keys |

---

## Production Roadmap

See [`docs/superpowers/specs/2026-03-22-production-roadmap-design.md`](docs/superpowers/specs/2026-03-22-production-roadmap-design.md) for detailed roadmap.

### Phase 1: Foundation ✅
- [x] Data infrastructure
- [x] Multi-strategy framework
- [x] Backtesting engine
- [x] Portfolio risk management

### Phase 2: Execution ✅
- [x] CTF integration
- [x] Order management
- [x] Reconciliation
- [x] Shadow mode
- [x] ECS deployment

### Phase 3: Production ✅
- [x] Observability
- [x] Scaling automation
- [x] CI/CD pipeline
- [x] Disaster recovery

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Disclaimer

**⚠️ Risk Warning**

This software is provided for **research and educational purposes**. Prediction markets and cryptocurrency systems carry significant financial and operational risks:

- **Financial Risk**: Automated trading can result in substantial losses
- **Smart Contract Risk**: Blockchain interactions carry inherent technical risks  
- **Market Risk**: Prediction markets are volatile and can be unpredictable
- **Operational Risk**: Software bugs or infrastructure failures may occur

**Use at your own risk.** Always start with paper trading and shadow mode before considering live execution. Never risk capital you cannot afford to lose.

---

## Support & Community

- **Issues**: [GitHub Issues](https://github.com/G3niusYukki/PolyClaw/issues)
- **Discussions**: [GitHub Discussions](https://github.com/G3niusYukki/PolyClaw/discussions)
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md)

---

<p align="center">
  <sub>Built with ❤️ for the prediction market community</sub>
</p>
