# Live CTF Execution — Real Money Integration

**Date:** 2026-03-23
**Status:** Approved
**Owner:** PolyClaw

## Overview

Replace all mock CTF/blockchain integrations with real Polygon RPC calls. The system remains in shadow mode by default; live trading is gated behind explicit configuration and safety controls.

**Scope:** P0 only —打通真实 CTF 下单、签名、持仓/余额/撤单查询、成交状态查询、对账、保护层、真钱验证。

## Architecture

### Before → After

| Layer | Before | After |
|-------|--------|-------|
| Signing | `sha256(...)` mock | `eth-account` secp256k1 ECDSA |
| Address derivation | `sha256(pk)` mock | Real public key → address |
| Order submission | `_simulate_ctf_submission()` returns fake hash | `eth_sendRawTransaction` → real tx hash |
| Fill status | Fake by tx hash | `eth_getTransactionReceipt` polling |
| Positions | Returns `[]` | `eth_call` CTF contract `getBalance` |
| Balances | Returns fake numbers | `eth_getBalance` (USDC, MATIC) |
| Order cancellation | No-op | `eth_sendTransaction` → CTF `cancelOrder` |
| Reconciliation | API + chain read same mock source | API from Polymarket, chain from CTF contract |

## Private Key Injection

**Environment variable only — never written to disk.**

```bash
export CTF_PRIVATE_KEY=0x78bffecc7e1c0fa7fb1d406520771c44faa3fc48cb62a9ff026e11030186a065
```

`WalletSigner.__init__()` reads from `secrets_manager.get_ctf_private_key()` which falls back to `CTF_PRIVATE_KEY` env var.

### Startup Validation

- Format check: 64-character hex string
- Derived address check: non-zero address (not `0x0000...`)
- When `live_trading_enabled=true` and private key is missing or malformed: **raise `ValueError` and refuse to start** — do not silently fall back to mock mode

### RPC Configuration

- **Dev:** Public node `https://polygon-rpc.com` (rate-limited, no API key)
- **Prod:** Alchemy (or equivalent) with API key via `POLYGON_RPC_URL` env var

## Signing Implementation

Use `eth-account` library (pure Python, no native deps, already available as transitive dep):

```python
from eth_account import Account

class WalletSigner:
    def __init__(self, private_key: str | None = None):
        self._key = private_key  # hex string with or without 0x
        if self._key:
            self._account = Account.from_key(self._key)
        else:
            self._account = None

    @property
    def address(self) -> str:
        if self._account:
            return self._account.address  # auto-derived from pubkey
        return "0x" + "0" * 40

    def sign_transaction(self, tx_data: dict) -> str:
        """Sign an Ethereum transaction. Returns RLP-encoded signed transaction hex.

        Uses `rawTransaction.hex()` which is the full wire-format hex string
        accepted by eth_sendRawTransaction.
        """
        if not self._account:
            raise ValueError("Cannot sign: no private key configured")
        signed = self._account.sign_transaction(tx_data)
        return signed.rawTransaction.hex()
```

### Nonce Management

Fetch `nonce` per submission via `eth_getTransactionCount(signer_address, "pending")`.
Do not maintain a local counter — concurrent or sequential rapid orders must each re-fetch to avoid nonce gaps or collisions. The RPC call is atomic per order submission.

## Order Submission Flow

**Polygon chain ID: 137**

```
OrderSpec.to_ctf_payload()
  → build unsigned tx dict
    {
      to:         CTF_CONTRACT_ADDRESS,
      data:       ABI-encode(createOrder(...)),
      chainId:    137,
      nonce:      eth_getTransactionCount(signer, "pending"),
      type:       2,                         # EIP-1559
      maxFeePerGas:         eth_maxPriorityFeePerGas + 2 * eth_baseFee,
      maxPriorityFeePerGas: eth_maxPriorityFeePerGas,
      gas:        estimate via eth_estimateGas, fallback 500000,
      value:      0
    }
  → WalletSigner.sign_transaction(tx_dict)
  → POST eth_sendRawTransaction [raw_tx_hex]
  → tx_hash
  → poll eth_getTransactionReceipt every 2s, timeout 120s
  → parse receipt {status, gasUsed, logs}
  → map to OrderUpdate {filled/rejected/partial}
  → write to DB
```

**Gas strategy:** Always use EIP-1559 (type 2). Fetch `eth_maxPriorityFeePerGas` and `eth_baseFee` per transaction. Polygon block time ≈ 2s so gas should be fresh on each call.

### CTF Contract ABI

CTF contract address: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
Polygon chain ID: **137**

Minimal ABI fragment needed:

```json
[
  {
    "name": "createOrder",
    "type": "function",
    "inputs": [
      {"name": "market", "type": "address"},
      {"name": "outcome", "type": "uint256"},
      {"name": "amount", "type": "uint256"},
      {"name": "price", "type": "uint256"}
    ]
  },
  {
    "name": "cancelOrder",
    "type": "function",
    "inputs": [
      {"name": "marketHash", "type": "bytes32"},
      {"name": "outcome", "type": "uint256"},
      {"name": "price", "type": "uint256"}
    ]
  },
  {
    "name": "getBalance",
    "type": "function",
    "inputs": [
      {"name": "trader", "type": "address"},
      {"name": "market", "type": "address"},
      {"name": "outcome", "type": "uint256"}
    ],
    "stateMutability": "view"
  },
  {
    "name": "getCollateralBalance",
    "type": "function",
    "inputs": [{"name": "trader", "type": "address"}],
    "stateMutability": "view"
  },
  {
    "name": "getOrder",
    "type": "function",
    "inputs": [
      {"name": "trader", "type": "address"},
      {"name": "marketHash", "type": "bytes32"},
      {"name": "price", "type": "uint256"},
      {"name": "outcome", "type": "uint256"}
    ],
    "stateMutability": "view"
  }
]
```

All integer values are raw (no decimals). USDC uses 6 decimals: `raw / 1_000_000`.

Key methods called via `eth_call` / `eth_sendTransaction`:

| Method | Type | Purpose |
|--------|------|---------|
| `createOrder(market, outcome, amount, price)` | send | Submit new order |
| `cancelOrder(marketHash, outcome, price)` | send | Cancel existing order |
| `getBalance(trader, market, outcome)` | call | Position size |
| `getCollateralBalance(trader)` | call | USDC balance |
| `getOrder(trader, marketHash, price, outcome)` | call | Order status |

## Protected Failure Modes

New circuit-breaker trigger conditions (in addition to existing ones):

| Trigger | Threshold | Action |
|---------|-----------|--------|
| `eth_sendTransaction` consecutive failures | 3 | GlobalCircuitBreaker |
| `eth_getTransactionReceipt` timeout | 120s no confirmation | Alert + log; 300s → kill switch |
| Insufficient balance | `balance < order_size` | Reject order, alert |
| Signing exception | Any unhandled exception in `sign_transaction` | Kill switch immediately |
| RPC consecutive errors | 5 errors in 10 min | Kill switch |
| Reconciliation drift | API vs chain > $10 | Alert; > $50 → kill switch |

All failures logged to `AuditLog` with `component="ctf_live"`.

## Real-Money Verification Test

Before shadow→live stage upgrade, execute and document:

1. Submit one $1 USDC buy order manually via API
2. Confirm `eth_getTransactionReceipt` shows `status=1`
3. Confirm `get_positions()` returns correct size
4. Confirm `get_balances()` returns correct USDC
5. Confirm reconciliation shows zero drift
6. Cancel the test position manually
7. Log tx hash, block number, and timestamps

## RPC Error Handling

- All RPC calls wrapped in `try/except` with typed exception `RPCCallError`
- `eth_sendTransaction`: retry once on network error, then fail
- `eth_getTransactionReceipt`: exponential backoff, 2s → 4s → 8s → 16s, max 15 retries
- RPC timeout: 30s per call
- On RPC error: increment `rpc_error_count`, reset on success

## Dependency Changes

Add to `pyproject.toml`:
- `eth-account>=0.11` — pure Python signing
- `eth-typing>=4.0` — type stubs

## Phases

### Phase 1: Real signing (`signer.py`)
- Replace SHA256 mock with `eth-account`
- Add startup validation with fail-on-live
- Test: derive address matches expected

### Phase 2: Real submission + fill status (`ctf.py`)
- Replace `_simulate_ctf_submission()` with real `eth_sendRawTransaction`
- Replace fake fill status with `eth_getTransactionReceipt` polling
- Test: submit real test transaction, confirm tx on Polygonscan

### Phase 3: Real positions, balances, cancellation (`ctf.py`)
- Replace `_query_ctf_positions()` with `eth_call` to CTF contract
- Replace `_query_ctf_balances()` with `eth_getBalance`
- Replace `_cancel_ctf_order()` with real `eth_sendTransaction`
- Test: query positions/balances match Polygonscan

### Phase 4: Real reconciliation (`reconciliation/service.py`)
- `get_chain_positions()` reads from real `get_positions()`
- `get_api_positions()` reads from real Polymarket API
- Add drift detection and alerting
- Test: submit order, verify API and chain positions match

### Phase 5: Protection layer hardening
- Add new circuit breaker conditions
- Add RPC error counting and kill switch
- Test: simulate RPC failure, verify circuit breaker trips

### Phase 6: End-to-end verification
- Execute real-money verification test
- Document tx hash, results, timing
- Confirm full signal→order→fill→reconciliation chain

## Out of Scope (P1/P2)

- CLI test coverage
- Integration test + fault injection
- DR recovery drills
- Multi-strategy budget isolation
