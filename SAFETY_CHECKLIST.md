# PolyClaw Safety Checklist

## Before enabling anything beyond paper mode

- [ ] No private keys or seed phrases stored in code or repo
- [ ] Child wallet / limited-risk wallet only
- [ ] `live_trading_enabled=true` set explicitly by operator
- [ ] Approval gate reviewed
- [ ] Kill switch tested
- [ ] Daily loss limit tested
- [ ] Consecutive failure halt tested
- [ ] Stale data rejection tested
- [ ] Low-liquidity rejection tested
- [ ] Audit logs visible and queryable
- [ ] Rollback path documented

## Live trading prerequisites (before enabling `LIVE_TRADING_ENABLED=true`)

These checks are enforced by `LiveTradingPrerequisites` at startup. Run manually to verify:

```bash
python -c "from polyclaw.providers.prerequisites import LiveTradingPrerequisites; LiveTradingPrerequisites().run_all()"
```

- [ ] **RPC reachable** — `eth_blockNumber` JSON-RPC call succeeds (not a 404 from a health endpoint)
- [ ] **CTF contract address verified** — matches `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` on Polyscan
- [ ] **CTF selectors confirmed** — `createOrder=0x6f652e1a`, `cancelOrder=0x0fdb031d` match the on-chain ABI
- [ ] **USDC balance queryable** — `eth_call` to `getBalance(address)` returns a non-negative balance
- [ ] **MATIC balance sufficient** — enough MATIC for gas (at least 0.01 MATIC recommended)
- [ ] **`_build_call_data` outcome encoding verified** — `outcome` (1=yes, 2=no) is encoded as `0x...` padded 32-byte hex between `market_hash` and `amount`, producing a 266-char calldata hex string
- [ ] Closed-loop smoke test passes (`pytest polyclaw/tests/test_live_smoke.py -v -s -m live_manual`)

## Reconciliation gating

Live trading is blocked when either position source is unreachable:

- [ ] **Polymarket API reachable** — `get_positions()` via `PolymarketGammaProvider` returns data
- [ ] **CTF chain reachable** — `get_positions()` via `PolymarketCTFProvider._query_ctf_positions()` returns data
- [ ] Reconciliation drift below `$10 auto-close threshold` — run `POST /reconciliation/run` and check `total_drift_usd`

## Shadow mode validation (before any live capital at risk)

- [ ] Shadow mode enabled (`SHADOW_MODE_ENABLED=true`, `SHADOW_STAGE=0`)
- [ ] Signal accuracy >60% after 50+ shadow trades (`GET /shadow/accuracy`)
- [ ] Position reconciliation passes in shadow mode with zero drift
- [ ] Transition to live approved by operator after accuracy validation

## v1 release policy

- Default to paper mode
- Default to manual approval
- Do not enable unattended live trading in v1
- Only allow high-liquidity markets
- Start with small notional and staged rollout
