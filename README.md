# PolyClaw

PolyClaw is a practical MVP for a **Polymarket auto-analysis + guarded execution system**. It is designed around a closed loop:

1. Ingest markets from a provider
2. Enrich with evidence from news / research sources
3. Score opportunity + confidence
4. Apply risk controls
5. Create orders in paper mode or guarded live mode
6. Record positions, fills, and decisions for review

> Default mode is **paper trading**. Live execution is intentionally gated behind configuration and risk controls.

## Features

- Pluggable providers for markets, evidence, and execution
- SQLite persistence via SQLAlchemy
- FastAPI service for health, scans, decisions, approvals, and positions
- Risk engine with stale data checks, spread/liquidity thresholds, exposure caps, and confidence floors
- Strategy engine with explainable scoring
- Paper executor for safe dry runs
- Optional approval gate before execution
- Kill switch and audit log primitives
- Tests for core decision and risk logic

## Architecture

```text
providers -> analysis -> risk -> order planner -> approval gate -> executor -> storage -> API/reporting
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn polyclaw.api.main:app --reload
```

Then visit:

- `GET /health`
- `POST /scan`
- `GET /markets`
- `GET /decisions`
- `POST /decisions/{id}/approve`
- `POST /runner/tick`
- `POST /execute-ready`
- `GET /audit-logs`
- `GET /kill-switch`
- `POST /kill-switch/enable`
- `POST /kill-switch/disable`

Or run a full scheduler-style cycle from CLI:

```bash
polyclaw tick
```

## Safe defaults

- `EXECUTION_MODE=paper`
- `REQUIRE_APPROVAL=true`
- `AUTO_EXECUTE=false`
- `LIVE_TRADING_ENABLED=false`

To move toward automation, first disable approval in **paper mode**, review behavior, and only later add a real executor implementation.

## Suggested next steps

1. Implement real Polymarket market ingestion
2. Implement evidence adapters (news, official sources, social with trust scores)
3. Implement live execution adapter with dry-run parity
4. Add backtesting and calibration
5. Add portfolio correlation limits by event family

## Disclaimer

This software is for research and controlled automation. Prediction markets and crypto-linked systems carry significant financial and operational risk.
