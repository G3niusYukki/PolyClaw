<p align="center">
  <img src="https://img.shields.io/badge/PolyClaw-v0.2.0-blue?style=for-the-badge" alt="PolyClaw">
  <br>
  <strong>Multi-Strategy Polymarket Trading Framework</strong>
  <br>
  <em>LLM-powered analysis, on-chain smart money tracking, and cross-platform arbitrage</em>
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick%20Start-Guide-orange?style=flat-square" alt="Quick Start"></a>
  <a href="#strategies"><img src="https://img.shields.io/badge/Strategies-6%20Active-green?style=flat-square" alt="Strategies"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/Tests-513%20passing-brightgreen?style=flat-square" alt="Tests">
</p>

---

## Overview

**PolyClaw** is an algorithmic trading framework for [Polymarket](https://polymarket.com) prediction markets. It combines multiple signal sources — LLM probability estimation, news sentiment analysis, on-chain smart money tracking, and cross-platform price comparison — to find exploitable edges.

> **Default mode: paper trading.** Live execution is gated behind multiple safety layers.

### What makes it different

- **LLM-driven probability estimation** — uses GPT-4o / Claude to estimate event probabilities, compared against market prices
- **News sentiment integration** — fetches real-time news and analyzes directional impact
- **Smart money tracking** — monitors whale wallets and on-chain activity on Polygon
- **Cross-platform arbitrage** — compares Polymarket prices with Manifold, Metaculus, and Kalshi
- **Multi-signal alignment** — strategies only fire when multiple independent signals agree on direction

---

## Strategies

| Strategy | Signal Source | Requires | Status |
|----------|--------------|----------|--------|
| **LLM Probability** | LLM probability estimate vs market price | `LLM_API_KEY` | Active |
| **News Catalyst** | LLM baseline + news sentiment (60/40 blend) | `LLM_API_KEY` + `NEWS_FETCHER_ENABLED` | Active |
| **Smart Money** | On-chain whale positions + LLM alignment | `LLM_API_KEY` + `ONCHAIN_TRACKING_ENABLED` | Active |
| **Cross-Platform Arb** | Price discrepancy across platforms | `LLM_API_KEY` + `CROSS_PLATFORM_ENABLED` | Active |
| **Event Catalyst** | Event timing and market characteristics | — | Built-in |
| **Liquidity Momentum** | Volume surge + price momentum composite | — | Built-in |

### Signal Architecture

```
Market Data ──▶ Strategy ──▶ Signal (side, confidence, edge_bps)
                   │
                   ├── LLM Probability: edge = |llm_prob - market_price| × 10000
                   ├── News Catalyst: 60% LLM + 40% sentiment, direction alignment required
                   ├── Smart Money: on-chain signals aligned with LLM direction
                   └── Cross-Platform: Polymarket vs consensus of 2+ platforms

Signal ──▶ Risk Engine ──▶ Approval Gate ──▶ Paper/Live Execution
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Optional] LLM API key (OpenAI or Anthropic) for advanced strategies

### Installation

```bash
git clone https://github.com/G3niusYukki/PolyClaw.git
cd PolyClaw
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Edit .env — at minimum set LLM_API_KEY for LLM-based strategies
```

Key settings in `.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `EXECUTION_MODE` | `paper` | `paper` or `live` |
| `LLM_PROVIDER` | `openai` | `openai` or `anthropic` |
| `LLM_API_KEY` | _(empty)_ | API key for LLM strategies |
| `LLM_MODEL` | `gpt-4o` | Model to use |
| `NEWS_FETCHER_ENABLED` | `false` | Enable news sentiment strategy |
| `ONCHAIN_TRACKING_ENABLED` | `false` | Enable smart money strategy |
| `CROSS_PLATFORM_ENABLED` | `false` | Enable cross-platform arbitrage |

### Run

```bash
# Start API server
uvicorn polyclaw.api.main:app --reload

# Run analysis cycle
polyclaw tick

# Run backtest
polyclaw backtest --strategy llm_probability
```

### Docker

```bash
docker-compose up -d
```

Uses SQLite by default. No external database required.

---

## Architecture

```
polyclaw/
├── api/              FastAPI REST endpoints
├── backtest/         Backtesting with walk-forward validation
├── data/
│   ├── news_fetcher.py    Google News RSS fetcher
│   ├── sentiment.py       LLM sentiment analysis
│   ├── onchain.py         Polygon RPC on-chain analyzer
│   └── cross_platform.py  Multi-platform price fetcher
├── execution/        Order state machine, retry, price bands
├── llm/
│   ├── client.py     Unified OpenAI/Anthropic client with retry
│   ├── prompts.py    Probability estimation prompts
│   └── parser.py     JSON response extraction
├── providers/        Polymarket Gamma API, CTF execution
├── risk/             Risk engine, Kelly sizing, portfolio limits
├── shadow/           Shadow mode engine for simulated execution
├── strategies/
│   ├── base.py       BaseStrategy ABC
│   ├── registry.py   StrategyRegistry singleton
│   ├── llm_probability.py
│   ├── news_catalyst.py
│   ├── smart_money.py
│   ├── cross_platform_arb.py
│   ├── event_catalyst.py
│   └── liquidity_momentum.py
└── services/         AnalysisService orchestrator
```

### Data Flow

```
Polymarket API ──▶ MarketFetcher ──▶ MarketRanker
                                           │
                    ┌──────────────────────┤
                    ▼                      ▼
              FeatureEngine          EvidenceEngine
                    │                      │
            ┌───────┼───────┐             │
            ▼       ▼       ▼             │
         LLM    News    On-chain          │
         Client  Fetcher  Analyzer        │
            │       │       │             │
            ▼       ▼       ▼             │
        Strategies generate signals       │
                    │                      │
                    ▼                      ▼
              RiskEngine ◄── Evidence
                    │
                    ▼
             Approval Gate ──▶ Paper/Live Execution
```

---

## Safety

PolyClaw has 9 safety layers, all defaulting to conservative values:

1. **Paper mode by default** — `EXECUTION_MODE=paper`
2. **Approval gate** — every decision requires manual approval
3. **Kill switch** — emergency stop via API
4. **Global circuit breaker** — triggers on portfolio DD >20%, daily loss >$500
5. **Strategy circuit breaker** — per-strategy with auto-reset after 24h
6. **Price band validator** — rejects orders >2% from reference price
7. **Reconciliation gating** — blocks trading when data sources unavailable
8. **Market whitelist** — default deny, only whitelisted markets for live
9. **Staged position sizing** — gradual capital deployment (shadow → 10% → 25% → ...)

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/health/detailed` | GET | Component health status |
| `/scan` | POST | Run market analysis cycle |
| `/candidates` | GET | Ranked market opportunities |
| `/proposals` | GET | Proposal previews |
| `/decisions` | GET | Trading decisions |
| `/execute-ready` | POST | Execute approved decisions |
| `/orders` | GET | Order tracking |
| `/positions` | GET | Current positions |
| `/shadow/results` | GET | Shadow mode performance |
| `/reports/pnl` | GET | PnL reports |
| `/kill-switch` | GET/POST | Emergency stop |

Interactive docs at `http://localhost:8000/docs` (Swagger UI).

---

## Development

```bash
# Run tests
pytest

# With coverage
pytest --cov=polyclaw --cov-fail-under=80

# Lint
ruff check polyclaw/

# Type check
mypy polyclaw/

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

## Disclaimer

This software is for **research and educational purposes**. Prediction markets carry significant financial risk. Always start with paper trading. Never risk capital you cannot afford to lose.
