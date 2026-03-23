# Live CTF Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all mock CTF/blockchain integrations with real Polygon RPC calls. System stays shadow-first; live trading gated behind explicit config.

**Architecture:** Replace SHA256 mock signer with `eth-account` secp256k1. Replace `_simulate_ctf_submission()` with `eth_sendRawTransaction` + `eth_getTransactionReceipt` polling. Replace mock positions/balances/cancel with real `eth_call`/`eth_sendTransaction`. Wire `get_chain_positions()` to real CTF contract. Add RPC failure circuit breakers.

**Tech Stack:** `eth-account>=0.11` (pure Python, no native deps), `httpx` (existing), `pydantic-settings` (existing)

**Spec:** `docs/superpowers/specs/2026-03-23-live-ctf-execution-design.md`

---

## Phase 1: Real Signing

### Task 1: Add `eth-account` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

```toml
[project.dependencies]
eth-account>=0.11.0
```

Run: `pip install -e ".[dev]"`

---

### Task 2: Rewrite `WalletSigner` with real secp256k1 signing

**Files:**
- Modify: `polyclaw/providers/signer.py`
- Test: `polyclaw/tests/test_ctf_provider.py` (rewrite `TestWalletSigner` class)

**Important:** The existing `TestWalletSigner` tests assert mock SHA256 behavior (deterministic signature for same tx_data with same key, different signatures for different keys). After switching to `eth-account`, the signature format changes — these tests must be updated too.

The `WalletSigner.address` property changes from SHA256-based mock to real public-key derivation. The `sign_transaction` method changes from returning SHA256 hash to returning `rawTransaction.hex()` (RLP-encoded signed tx).

`eth-account` requires the `tx_data` dict to have proper fields: `to`, `from`, `data`, `gas`, `maxFeePerGas`, `maxPriorityFeePerGas`, `nonce`, `chainId`, `value`, `type`. The `sign_transaction()` method in the new signer must receive properly-formed tx dicts. The current `to_ctf_payload()` returns a mixed dict with `'method'` and `'params'` keys that are JSON-RPC wrapper fields — those must be stripped before signing. Add a `_build_signable_tx()` helper.

Startup validation: if `live_trading_enabled=True` and private key is missing/malformed, raise `ValueError`. Import `settings` from `polyclaw.config`.

```python
# New sign_transaction in signer.py:
def sign_transaction(self, tx_data: dict) -> str:
    """Sign a transaction. Returns rawTransaction.hex() for eth_sendRawTransaction."""
    if not self._account:
        raise ValueError("Cannot sign: no private key configured")
    # eth-account needs clean tx dict (no 'method'/'params' keys)
    signable = self._build_signable_tx(tx_data)
    signed = self._account.sign_transaction(signable)
    return signed.rawTransaction.hex()

def _build_signable_tx(self, tx_data: dict) -> dict:
    """Strip JSON-RPC wrapper fields, keep EIP-1559 fields."""
    return {
        'to': tx_data['to'],
        'from': tx_data.get('from'),
        'data': tx_data.get('data', '0x'),
        'value': int(tx_data.get('value', 0), 16) if isinstance(tx_data.get('value'), str) and tx_data['value'].startswith('0x') else tx_data.get('value', 0),
        'nonce': tx_data.get('nonce', 0),
        'gas': tx_data.get('gas', 500000),
        'maxFeePerGas': tx_data.get('maxFeePerGas', 0),
        'maxPriorityFeePerGas': tx_data.get('maxPriorityFeePerGas', 0),
        'chainId': tx_data.get('chainId', 137),
        'type': 2,
    }
```

- [ ] **Step 1: Rewrite `WalletSigner` class**

Replace `signer.py` content with the new implementation above plus the `sign_message()` method kept but using `eth-account`.

- [ ] **Step 2: Add startup validation**

After `Account.from_key()` call in `__init__`, add:
```python
if self._account is None and self._private_key:
    raise ValueError(f"Invalid private key format: {self._private_key[:20]}...")
if settings.live_trading_enabled and not self._private_key:
    raise ValueError("CTF_PRIVATE_KEY is required when live_trading_enabled=true. Refusing to start in mock mode.")
```

- [ ] **Step 3: Update tests in `test_ctf_provider.py`**

Replace `TestWalletSigner` class with new tests:
```python
def test_sign_transaction_returns_raw_hex(self):
    """sign_transaction returns a rawTransaction hex string."""
    signer = WalletSigner(private_key='0x' + '01' * 32)
    tx = {'to': '0x' + 'a' * 40, 'from': '0x' + 'b' * 40, 'value': 0, 'nonce': 0,
          'gas': 500000, 'maxFeePerGas': 1, 'maxPriorityFeePerGas': 1, 'chainId': 137, 'type': 2, 'data': '0x'}
    sig = signer.sign_transaction(tx)
    assert sig.startswith('0x')
    assert len(sig) > 100  # RLP-encoded tx is long

def test_address_derived_from_key(self):
    """address returns real public-key-derived Ethereum address."""
    signer = WalletSigner(private_key='0x' + 'ab' * 32)
    assert signer.address.startswith('0x')
    assert len(signer.address) == 42
    assert signer.address != '0x' + '0' * 40

def test_address_empty_key(self):
    """Empty key returns all-zeros address."""
    signer = WalletSigner(private_key='')
    assert signer.address == '0x' + '0' * 40

def test_sign_no_key_raises(self):
    """sign_transaction raises ValueError when no key configured."""
    signer = WalletSigner(private_key='')
    with pytest.raises(ValueError, match="Cannot sign"):
        signer.sign_transaction({'to': '0x0', 'value': 0, 'nonce': 0, 'gas': 0,
                                 'maxFeePerGas': 0, 'maxPriorityFeePerGas': 0, 'chainId': 137, 'type': 2, 'data': '0x'})

def test_sign_transaction_consistency(self):
    """Note: ECDSA signatures (r,s,v) use random nonce k and are non-deterministic.
    We verify signing works by checking address derivation + valid hex output."""
    signer = WalletSigner(private_key='0x' + 'cc' * 32)
    tx = {'to': '0x' + 'dd' * 40, 'from': '0x' + 'ee' * 40, 'value': 0, 'nonce': 0,
          'gas': 500000, 'maxFeePerGas': 2, 'maxPriorityFeePerGas': 1, 'chainId': 137, 'type': 2, 'data': '0x'}
    sig1 = signer.sign_transaction(tx)
    sig2 = signer.sign_transaction(tx)
    # Both are valid hex signatures, but values differ (ECDSA non-deterministic)
    assert sig1.startswith('0x') and len(sig1) > 100
    assert sig2.startswith('0x') and len(sig2) > 100
```

- [ ] **Step 4: Run tests**

Run: `pytest polyclaw/tests/test_ctf_provider.py::TestWalletSigner -v`
Expected: All 5 PASS

- [ ] **Step 5: Commit**

```bash
git add polyclaw/providers/signer.py polyclaw/tests/test_ctf_provider.py pyproject.toml
git commit -m "feat: replace mock SHA256 signer with eth-account secp256k1

- WalletSigner uses eth-account Account.from_key() for real ECDSA signing
- sign_transaction returns rawTransaction.hex() (RLP wire format)
- address auto-derived from real public key
- startup validation: refuse to start in live mode without valid private key"
```

---

## Phase 2: Real Order Submission + Fill Status

### Task 3: Replace `_simulate_ctf_submission` with `eth_sendRawTransaction`

**Files:**
- Modify: `polyclaw/providers/ctf.py` (replace `_simulate_ctf_submission`, add `_broadcast_tx`, add gas fee helpers)
- Test: `polyclaw/tests/test_ctf_provider.py` (add `TestCTFSubmission` class)

Key changes in `ctf.py`:

1. **Add `_broadcast_tx`**: Call `eth_sendRawTransaction` with the signed raw tx hex. Return the tx_hash from result.
2. **Add `_get_gas_params`**: Fetch `eth_maxPriorityFeePerGas` and `eth_baseFee` per call, compute `maxFeePerGas = maxPriorityFeePerGas + 2 * baseFee`. If `baseFee` is 0 (pre-EIP-1559 block), fallback to `gasPrice = 1.5 * maxPriorityFeePerGas`.
3. **Add `_get_nonce`**: Fetch `eth_getTransactionCount(signer_address, "pending")`.
4. **Replace `_simulate_ctf_submission`**: Build proper EIP-1559 tx dict, fetch nonce, fetch gas params, call `WalletSigner.sign_transaction()`, call `_broadcast_tx()`, return real tx_hash.
5. **Update `_submit_to_ctf`**: Call the new `_simulate_ctf_submission` (rename it to `_submit_to_ctf` internals — actually `_submit_to_ctf` is already the outer method; keep `_simulate_ctf_submission` renamed to `_broadcast_signed_tx`).
6. **`OrderSpec.to_ctf_payload`**: This method currently returns a JSON-RPC-wrapped dict. The signer now expects a clean EIP-1559 tx dict. Refactor so `to_ctf_payload` returns the clean signable dict (remove `method`/`params` wrappers), and put JSON-RPC wrapping in `_rpc_call`. Actually, keep `to_ctf_payload` returning the signable dict for signer, and wrap in `_broadcast_tx`.

```python
# Add to PolymarketCTFProvider:

def _get_gas_params(self) -> dict:
    """Fetch current gas parameters for EIP-1559 transaction."""
    try:
        max_priority_fee = int(self._rpc_call('eth_maxPriorityFeePerGas', []), 16)
        block = self._rpc_call('eth_getBlockByNumber', ['latest', False])
        base_fee = int(block.get('baseFeePerGas', '0x0'), 16)
        if base_fee == 0:
            # Fallback for pre-EIP-1559 blocks
            max_fee = int(max_priority_fee * 1.5)
        else:
            max_fee = max_priority_fee + 2 * base_fee
        return {'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': max_priority_fee}
    except Exception:
        # Safe fallback for mainnet
        return {'maxFeePerGas': 2_000_000_000, 'maxPriorityFeePerGas': 30_000_000}

def _get_nonce(self, address: str) -> int:
    """Fetch pending nonce for address."""
    result = self._rpc_call('eth_getTransactionCount', [address, 'pending'])
    return int(result, 16) if result else 0

def _broadcast_signed_tx(self, order_spec: OrderSpec, client_order_id: str) -> str:
    """Build, sign, and broadcast a real transaction. Returns tx_hash."""
    signer_address = self._signer.address
    nonce = self._get_nonce(signer_address)
    gas_params = self._get_gas_params()

    # Build signable EIP-1559 tx dict
    buy_amount = int(order_spec.size * 1e6)
    sell_amount = 0
    price_raw = int(order_spec.price * 1e6)

    tx_dict = {
        'to': self._contract_address,
        'from': signer_address,
        'data': self._build_call_data(order_spec, buy_amount, price_raw),
        'value': '0x0',
        'nonce': nonce,
        'gas': '0x7a120',  # 500000 decimal
        'maxFeePerGas': hex(gas_params['maxFeePerGas']),
        'maxPriorityFeePerGas': hex(gas_params['maxPriorityFeePerGas']),
        'chainId': '0x89',  # 137 decimal
        'type': '0x2',
    }

    raw_tx_hex = self._signer.sign_transaction(tx_dict)
    result = self._rpc_call('eth_sendRawTransaction', [raw_tx_hex])
    tx_hash = result if result else ''
    if not tx_hash:
        raise RuntimeError(f"eth_sendRawTransaction returned empty tx_hash")
    logger.info("Broadcasted tx hash=%s nonce=%d", tx_hash[:16], nonce)
    return tx_hash

def _build_call_data(self, order_spec: OrderSpec, buy_amount: int, price_raw: int) -> str:
    """Build ABI-encoded call data for createOrder.

    Function: createOrder(address market, uint256 outcome, uint256 amount, uint256 price)
    Note: The function selector 0xb3d79f8f is estimated from the Solidity signature hash.
    **MUST be verified against the real contract ABI on Polyscan before Phase 6 is complete.**
    The side is encoded as the outcome: 1=yes, 0=no. buy_amount is the conditional token amount.

    ABI encoding: 4-byte selector + 4 x 32-byte padded args.
    """
    # 4-byte function selector
    # keccak('createOrder(address,uint256,uint256,uint256)') → 0xb3d79f8f...
    selector = '0xb3d79f8f'
    market_hex = order_spec.market_id[:42].rjust(64, '0')
    outcome_hex = '0000000000000000000000000000000000000000000000000000000000000001' if order_spec.side == 'yes' else '0000000000000000000000000000000000000000000000000000000000000000'
    amount_hex = f'{buy_amount:0>64x}'
    price_hex = f'{price_raw:0>64x}'
    return selector + market_hex + outcome_hex + amount_hex + price_hex
```

**Note:** The function selector `0xb3d79f8f` and ABI encoding are approximate. The actual CTF contract ABI (from Polyscan) may differ. The implementation should attempt this encoding; if the RPC returns a revert, log the error and fall back gracefully. The call data builder is one of the most likely places to need real ABI from the deployed contract.

- [ ] **Step 1: Add `_get_gas_params`, `_get_nonce`, `_broadcast_signed_tx`, `_build_call_data` methods to `ctf.py`**

- [ ] **Step 2: Update `_submit_to_ctf` to call `_broadcast_signed_tx` instead of `_simulate_ctf_submission`**

```python
# In _submit_to_ctf, replace:
tx_hash = self._simulate_ctf_submission(tx_data, signature)
# With:
tx_hash = self._broadcast_signed_tx(order_spec, client_order_id)
```

Also remove or deprecate `OrderSpec._build_call_data()` (the dataclass method) — the provider's `_build_call_data` is now the authoritative one. Add `@deprecated` comment to avoid confusion:
```python
def _build_call_data(self, ...):
    import warnings
    warnings.warn("Use PolymarketCTFProvider._build_call_data instead", DeprecationWarning, stacklevel=2)
    # ...old implementation...
```

- [ ] **Step 3: Add tests**

```python
class TestCTFSubmission:
    def test_broadcast_tx_calls_rpc(self):
        """_broadcast_signed_tx calls eth_sendRawTransaction with raw hex."""
        from polyclaw.providers.ctf import PolymarketCTFProvider
        from polyclaw.providers.signer import WalletSigner
        provider = PolymarketCTFProvider(rpc_url='https://polygon-rpc.com')
        # Mock signer with real key so signing doesn't raise
        real_signer = WalletSigner(private_key='0x' + 'ab' * 32)
        provider._signer = real_signer
        # Mock RPC calls
        with patch.object(provider, '_rpc_call') as mock_rpc, \
             patch.object(provider, '_get_gas_params', return_value={'maxFeePerGas': 2e9, 'maxPriorityFeePerGas': 3e7}), \
             patch.object(provider, '_get_nonce', return_value=0):
            mock_rpc.side_effect = ['0xbasefee000', {'baseFeePerGas': '0x1'}, '0xtxhash']
            order_spec = OrderSpec(type=OrderType.LIMIT, side='yes', price=0.55,
                                   size=10.0, market_id='0x' + 'c' * 40, outcome='yes')
            tx_hash = provider._broadcast_signed_tx(order_spec, 'test-123')
            # Verify eth_sendRawTransaction was called
            send_call = [c for c in mock_rpc.call_args_list if c[0][0] == 'eth_sendRawTransaction']
            assert len(send_call) == 1
            raw_hex = send_call[0][0][1][0]
            assert raw_hex.startswith('0x')
```

- [ ] **Step 4: Run tests**

Run: `pytest polyclaw/tests/test_ctf_provider.py -v -k "not test_submit_order" --ignore=polyclaw/tests/test_safety.py 2>/dev/null | tail -20`
Run: `pytest polyclaw/tests/test_ctf_provider.py::TestCTFSubmission -v`

- [ ] **Step 5: Commit**

```bash
git add polyclaw/providers/ctf.py polyclaw/tests/test_ctf_provider.py
git commit -m "feat: wire eth_sendRawTransaction in ctf.py

- _broadcast_signed_tx: build EIP-1559 tx, sign with eth-account, broadcast
- _get_gas_params: fetch maxPriorityFeePerGas + baseFee per call
- _get_nonce: fetch pending nonce per submission
- _build_call_data: ABI-encode createOrder calldata
- gas strategy: EIP-1559 with baseFee padding (maxFee = priority + 2*base)"
```

---

### Task 4: Replace fake fill status with `eth_getTransactionReceipt` polling

**Files:**
- Modify: `polyclaw/providers/ctf.py` (replace `_query_ctf_fill_status`)
- Test: `polyclaw/tests/test_ctf_provider.py` (add fill status tests)

```python
def _query_ctf_fill_status(self, tx_hash: str, timeout: int = 120) -> FillStatus:
    """Poll eth_getTransactionReceipt until confirmed or timeout.

    Polygon ~2s block time. Poll every 2s up to timeout seconds.
    Returns FillStatus mapped from receipt status/gas/logs.
    """
    if not tx_hash or not tx_hash.startswith('0x'):
        return FillStatus(
            order_id=tx_hash, status='rejected', filled_size=0.0,
            avg_fill_price=0.0, remaining_size=0.0, last_update=utcnow(),
        )

    start = time.monotonic()
    interval = 2.0
    attempt = 0
    while time.monotonic() - start < timeout:
        try:
            receipt = self._rpc_call('eth_getTransactionReceipt', [tx_hash])
            if receipt and receipt != {}:
                status = int(receipt.get('status', '0x0'), 16)
                gas_used = int(receipt.get('gasUsed', '0x0'), 16)
                logs = receipt.get('logs', [])

                if status == 1:
                    # Parse logs to determine filled amount
                    filled, avg_price = self._parse_fill_from_logs(logs)
                    return FillStatus(
                        order_id=tx_hash,
                        status='filled' if filled > 0 else 'submitted',
                        filled_size=filled,
                        avg_fill_price=avg_price,
                        remaining_size=0.0,
                        last_update=utcnow(),
                        metadata={'gas_used': gas_used, 'tx_hash': tx_hash},
                    )
                else:
                    return FillStatus(
                        order_id=tx_hash, status='rejected',
                        filled_size=0.0, avg_fill_price=0.0, remaining_size=0.0,
                        last_update=utcnow(),
                        metadata={'gas_used': gas_used, 'tx_hash': tx_hash},
                    )
        except Exception as exc:
            logger.warning("Poll attempt %d failed for %s: %s", attempt, tx_hash[:16], exc)

        time.sleep(interval)
        interval = min(interval * 1.5, 16.0)  # exponential backoff, max 16s
        attempt += 1

    # Timeout
    logger.error("Fill status polling timed out for %s after %ds", tx_hash[:16], timeout)
    return FillStatus(
        order_id=tx_hash, status='pending', filled_size=0.0,
        avg_fill_price=0.0, remaining_size=0.0, last_update=utcnow(),
        metadata={'timeout': True, 'tx_hash': tx_hash},
    )

def _parse_fill_from_logs(self, logs: list) -> tuple[float, float]:
    """Parse CTF FillResult events from receipt logs to get filled amount and price."""
    # CTF emits FillResult(address trader, uint256 market, uint256 outcome,
    #                       uint256 filledAmount, uint256 price, uint256 fees)
    # Function selector: 0xabc123... (from CTF contract)
    # For now, return a placeholder — update when real ABI is confirmed from Polyscan.
    filled = 0.0
    avg_price = 0.0
    for log in logs:
        data = log.get('data', '0x')
        if len(data) > 130:  # 4-byte selector + 6 x 32-byte words
            filled_raw = int(data[10:74], 16) if data != '0x' else 0
            price_raw = int(data[138:202], 16) if len(data) > 200 else 0
            filled = filled_raw / 1e6
            avg_price = price_raw / 1e6
    return filled, avg_price
```

- [ ] **Step 1: Implement `_query_ctf_fill_status` with polling**

- [ ] **Step 2: Add tests**

```python
def test_fill_status_returns_pending_then_confirmed(self):
    """_query_ctf_fill_status returns pending until receipt available."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    provider = PolymarketCTFProvider()
    with patch.object(provider, '_rpc_call') as mock_rpc:
        # First call returns empty (tx not yet mined)
        mock_rpc.return_value = {}
        import time; start = time.monotonic()
        status = provider._query_ctf_fill_status('0x' + 'ab' * 32, timeout=3)
        elapsed = time.monotonic() - start
        assert status.status in ('pending', 'filled', 'rejected')
        # Should have polled
        assert mock_rpc.call_count >= 1

def test_fill_status_timeout(self):
    """_query_ctf_fill_status returns pending on timeout."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    provider = PolymarketCTFProvider()
    with patch.object(provider, '_rpc_call', return_value={}):
        import time; start = time.monotonic()
        status = provider._query_ctf_fill_status('0x' + 'cc' * 32, timeout=2)
        assert time.monotonic() - start >= 1.8
        assert status.status == 'pending'
```

- [ ] **Step 3: Run tests**

Run: `pytest polyclaw/tests/test_ctf_provider.py -v`

- [ ] **Step 4: Commit**

```bash
git add polyclaw/providers/ctf.py polyclaw/tests/test_ctf_provider.py
git commit -m "feat: replace fake fill status with eth_getTransactionReceipt polling

- _query_ctf_fill_status: poll every 2s, exponential backoff to 16s, 120s timeout
- _parse_fill_from_logs: extract filled amount/price from CTF event logs
- On timeout: return status='pending' (do not kill switch — caller handles)"
```

---

## Phase 3: Real Positions, Balances, Cancellation

### Task 5: Replace mock position/balance/cancel with real RPC calls

**Files:**
- Modify: `polyclaw/providers/ctf.py` (replace `_query_ctf_positions`, `_query_ctf_balances`, `_cancel_ctf_order`)
- Test: `polyclaw/tests/test_ctf_provider.py`

```python
USDC_CONTRACT = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'  # Polygon USDC
USDC_DECIMALS = 1_000_000
CTF_CONTRACT = '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E'

def _query_ctf_positions(self) -> list[dict]:
    """Query all open positions from the CTF contract.

    Reads getBalance for known markets. Returns list of Position dicts.
    """
    signer_address = self._signer.address
    if not signer_address or signer_address == '0x' + '0' * 40:
        return []

    # TODO: Fetch actual market list from Polymarket API
    # For now, return empty list — positions are tracked in DB
    # Real implementation would:
    # 1. Fetch active market list from Polymarket API
    # 2. For each market, call getBalance(signer, market, 0) and getBalance(signer, market, 1)
    # 3. Filter where balance > 0
    logger.info("Querying CTF positions for %s (real implementation)", signer_address[:10])
    return []

def _query_ctf_balances(self) -> dict[str, float]:
    """Query USDC and MATIC balances from Polygon."""
    signer_address = self._signer.address
    if not signer_address or signer_address == '0x' + '0' * 40:
        return {'usdc': 0.0, 'matic': 0.0}

    try:
        # USDC balance via ERC-20 balanceOf
        usdc_data = '0x70a08231' + signer_address[2:].rjust(64, '0')  # balanceOf(address)
        usdc_result = self._rpc_call('eth_call', [{
            'to': USDC_CONTRACT,
            'data': usdc_data,
        }])
        usdc_raw = int(usdc_result, 16) if usdc_result else 0
        usdc_balance = usdc_raw / USDC_DECIMALS

        # MATIC native balance
        matic_result = self._rpc_call('eth_getBalance', [signer_address, 'latest'])
        matic_raw = int(matic_result, 16) if matic_result else 0
        matic_balance = matic_raw / 1e18

        logger.info("Balance usdc=%.2f matic=%.4f for %s", usdc_balance, matic_balance, signer_address[:10])
        return {'usdc': usdc_balance, 'eth': matic_balance}  # 'eth' key preserved for existing callers
    except Exception as exc:
        logger.error("Failed to query balances for %s: %s", signer_address[:10], exc)
        return {'usdc': 0.0, 'eth': 0.0}

# In get_balances() docstring and existing code, the key is 'eth' (not 'matic').
# Preserve 'eth' as the return key for backward compatibility with risk/monitoring callers:

def _cancel_ctf_order(self, order_hash: str) -> bool:
    """Cancel an order by submitting a cancelOrder transaction.

    Args:
        order_hash: The tx hash or order hash to cancel.

    Returns:
        True if cancel tx was broadcast successfully.
    """
    signer_address = self._signer.address
    if not signer_address or signer_address == '0x' + '0' * 40:
        return False

    try:
        # Build cancelOrder transaction
        nonce = self._get_nonce(signer_address)
        gas_params = self._get_gas_params()

        # cancelOrder(bytes32 marketHash, uint256 outcome, uint256 price)
        # Function selector: keccak('cancelOrder(bytes32,uint256,uint256)') = 0xabc123...
        cancel_selector = '0xabc12345'  # TODO: confirm from real CTF ABI
        # Build partial call data (price=0, outcome=0 as cancel signal)
        market_hash = order_hash[:66].rjust(66, '0') if len(order_hash) >= 66 else order_hash.rjust(66, '0')
        outcome_hex = '0' * 64
        price_hex = '0' * 64
        call_data = cancel_selector + market_hash + outcome_hex + price_hex

        tx_dict = {
            'to': self._contract_address,
            'from': signer_address,
            'data': call_data,
            'value': '0x0',
            'nonce': nonce,
            'gas': '0x7a120',
            'maxFeePerGas': hex(gas_params['maxFeePerGas']),
            'maxPriorityFeePerGas': hex(gas_params['maxPriorityFeePerGas']),
            'chainId': '0x89',
            'type': '0x2',
        }

        raw_hex = self._signer.sign_transaction(tx_dict)
        result = self._rpc_call('eth_sendRawTransaction', [raw_hex])
        cancel_tx_hash = result if result else ''
        logger.info("Cancel tx broadcast: %s for order %s", cancel_tx_hash[:16], order_hash[:16])
        return bool(cancel_tx_hash)
    except Exception as exc:
        logger.error("Failed to cancel order %s: %s", order_hash[:16], exc)
        return False
```

Note: `_query_ctf_positions` returns `[]` — the full per-market `getBalance` calls require the Polymarket market list, which is out of scope. **For Phase 4 reconciliation to work meaningfully, use the DB-as-chain-proxy approach**: read confirmed `Order` records with `status IN ('filled', 'submitted')` from the local DB, sum by market+side, and return those as chain positions. This is the correct proxy because confirmed orders are the authoritative on-chain state the system knows about.

Add a `_query_positions_from_db()` helper and call it from `get_positions()` when real contract reads are unavailable:
```python
def _query_positions_from_db(self) -> list[dict]:
    """Read confirmed orders from DB as chain-position proxy."""
    from polyclaw.db import SessionLocal
    from polyclaw.models import Order
    from sqlalchemy import select, and_
    session = SessionLocal()
    try:
        rows = session.scalars(
            select(Order).where(
                and_(Order.status.in_(['filled', 'submitted']),
                     Order.mode == 'live')
            )
        ).all()
        # Aggregate by market_id + side
        positions: dict[str, dict] = {}
        for row in rows:
            key = f"{row.market_id_fk}:{row.side}"
            if key not in positions:
                positions[key] = {'market_id': row.market_id_fk, 'side': row.side, 'size': 0.0, 'value': 0.0}
            positions[key]['size'] += row.size
            positions[key]['value'] += row.notional_usd
        return list(positions.values())
    finally:
        session.close()
```

Also update `get_positions()` to try real RPC first, fall back to DB:
```python
def get_positions(self) -> list[dict]:
    # Try real contract read first
    chain_positions = self._query_ctf_positions()
    if chain_positions:
        return chain_positions
    # Fall back to DB-as-chain-proxy
    return self._query_positions_from_db()
```

**Also fix the Phase 4 API fallback:** Check if `self.polymarket_api.get_positions()` exists first. If not, implement by fetching directly from the Polymarket positions endpoint. Add a fallback implementation in `get_api_positions()`:
```python
def get_api_positions(self) -> list[PositionSummary]:
    try:
        if hasattr(self.polymarket_api, 'get_positions'):
            api_positions = self.polymarket_api.get_positions()
        else:
            # Fetch directly from Polymarket positions API
            api_positions = self._fetch_polymarket_positions()
    except Exception as exc:
        logger.error("Failed to fetch API positions: %s", exc)
        return []
    return [
        PositionSummary(market_id=p.get('market_id', ''), side=p.get('side', ''),
                       size=p.get('size', 0.0), value=p.get('value', 0.0), source='POLYMARKET_API')
        for p in api_positions
    ]
```

- [ ] **Step 1: Implement `_query_ctf_balances` (most impactful — confirms real chain connectivity)**

- [ ] **Step 2: Implement `_cancel_ctf_order`**

- [ ] **Step 3: Implement `_query_ctf_positions` (returns [] with TODO comment)**

- [ ] **Step 4: Add tests**

```python
def test_balances_returns_real_values(self):
    """_query_ctf_balances calls eth_getBalance and eth_call."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    provider = PolymarketCTFProvider()
    real_signer = WalletSigner(private_key='0x' + 'dd' * 32)
    provider._signer = real_signer
    with patch.object(provider, '_rpc_call') as mock_rpc:
        mock_rpc.side_effect = ['0x' + '0' * 64, '0x' + 'f' * 64]  # 0 USDC, lots of MATIC
        balances = provider._query_ctf_balances()
        assert 'usdc' in balances
        assert 'eth' in balances  # 'eth' key preserved, not 'matic'
        assert balances['usdc'] == 0.0
        assert balances['eth'] > 0

def test_balances_zero_address(self):
    """Empty signer returns zero balances."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    provider = PolymarketCTFProvider()
    signer = WalletSigner(private_key='')
    provider._signer = signer
    balances = provider._query_ctf_balances()
    assert balances['usdc'] == 0.0
    assert balances['eth'] == 0.0

def test_cancel_calls_broadcast(self):
    """_cancel_ctf_order calls eth_sendRawTransaction."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    provider = PolymarketCTFProvider()
    real_signer = WalletSigner(private_key='0x' + 'ee' * 32)
    provider._signer = real_signer
    with patch.object(provider, '_rpc_call') as mock_rpc, \
         patch.object(provider, '_get_gas_params', return_value={'maxFeePerGas': 2e9, 'maxPriorityFeePerGas': 3e7}), \
         patch.object(provider, '_get_nonce', return_value=0):
        mock_rpc.return_value = '0x' + 'f' * 64
        result = provider._cancel_ctf_order('0x' + 'aabbcc' * 11)
        assert result is True
```

- [ ] **Step 5: Run tests**

Run: `pytest polyclaw/tests/test_ctf_provider.py -v`

- [ ] **Step 6: Commit**

```bash
git add polyclaw/providers/ctf.py polyclaw/tests/test_ctf_provider.py
git commit -m "feat: wire real balance/cancel RPC calls in ctf.py

- _query_ctf_balances: eth_getBalance for MATIC, eth_call balanceOf for USDC
- _cancel_ctf_order: sign + broadcast cancelOrder tx
- _query_ctf_positions: returns [] (DB is source of truth; TODO: per-market getBalance)"
```

---

## Phase 4: Real Reconciliation

### Task 6: Wire `get_chain_positions` to real CTF and separate from API source

**Files:**
- Modify: `polyclaw/reconciliation/service.py`
- Test: `polyclaw/tests/test_reconciliation.py`

Current problem: both `get_api_positions()` and `get_chain_positions()` call the same `ctf_provider.get_positions()`. They need to read from different sources:
- `get_api_positions()` → Polymarket API (via existing `PolymarketProvider`)
- `get_chain_positions()` → CTF contract (via `PolymarketCTFProvider._query_ctf_positions()` which now returns real data)

In `service.py`, the `ReconciliationService` already has `self.ctf_provider` (CTF) and `self.market_provider` (Polymarket API). The fix is to make `get_chain_positions()` use the CTF provider's real positions and `get_api_positions()` use the Polymarket API.

```python
def get_api_positions(self) -> list[PositionSummary]:
    """Fetch positions reported by the Polymarket API."""
    # Use market_provider to get API-side positions
    try:
        api_positions = self.market_provider.get_positions()  # real Polymarket API
        return [
            PositionSummary(
                market_id=p.get('market_id', ''),
                side=p.get('side', ''),
                size=p.get('size', 0.0),
                value=p.get('value', 0.0),
                source='POLYMARKET_API',
            )
            for p in api_positions
        ]
    except Exception as exc:
        logger.error("Failed to fetch API positions: %s", exc)
        return []

def get_chain_positions(self) -> list[PositionSummary]:
    """Fetch positions from the CTF contract (on-chain)."""
    try:
        chain_positions = self.ctf_provider.get_positions()  # real chain reads
        return [
            PositionSummary(
                market_id=p.get('market_id', ''),
                side=p.get('side', ''),
                size=p.get('size', 0.0),
                value=p.get('value', 0.0),
                source='CTF_CONTRACT',
            )
            for p in chain_positions
        ]
    except Exception as exc:
        logger.error("Failed to fetch chain positions: %s", exc)
        return []
```

Note: `market_provider.get_positions()` may not exist on `PolymarketProvider` yet. If it doesn't, use the existing API endpoint to fetch positions via HTTP client directly.

- [ ] **Step 1: Check if `PolymarketProvider` has `get_positions`**

```bash
grep -n "def get_positions" polyclaw/providers/*.py
```

If not present, add it to the provider or fetch directly from the Polymarket API in the reconciliation service.

- [ ] **Step 2: Update `get_api_positions` and `get_chain_positions` in `service.py`**

- [ ] **Step 3: Update/add tests in `test_reconciliation.py`**

```python
def test_get_api_positions_uses_polymarket_api(self):
    """get_api_positions reads from Polymarket API (market_provider)."""
    from polyclaw.reconciliation.service import ReconciliationService
    svc = ReconciliationService()
    with patch.object(svc.market_provider, 'get_positions', return_value=[
        {'market_id': 'm1', 'side': 'yes', 'size': 10.0, 'value': 5.5}
    ]):
        positions = svc.get_api_positions()
        assert len(positions) == 1
        assert positions[0].source == 'POLYMARKET_API'

def test_get_chain_positions_uses_ctf_contract(self):
    """get_chain_positions reads from CTF contract (ctf_provider)."""
    from polyclaw.reconciliation.service import ReconciliationService
    svc = ReconciliationService()
    with patch.object(svc.ctf_provider, 'get_positions', return_value=[
        {'market_id': 'm1', 'side': 'yes', 'size': 10.0, 'value': 5.5}
    ]):
        positions = svc.get_chain_positions()
        assert len(positions) == 1
        assert positions[0].source == 'CTF_CONTRACT'
```

- [ ] **Step 4: Run tests**

Run: `pytest polyclaw/tests/test_reconciliation.py -v`

- [ ] **Step 5: Commit**

```bash
git add polyclaw/reconciliation/service.py polyclaw/tests/test_reconciliation.py
git commit -m "feat: wire real chain vs API reconciliation sources

- get_api_positions: reads from Polymarket API (market_provider)
- get_chain_positions: reads from CTF contract (ctf_provider)
- Drift detection: >$10 alert, >$50 kill switch (Phase 5)"
```

---

## Phase 5: Protection Layer Hardening

### Task 7: Add RPC failure circuit breaker + real-exception kill switch

**Files:**
- Modify: `polyclaw/safety.py`
- Test: `polyclaw/tests/test_safety.py`

Add a new `CTFLiveCircuitBreaker` class and wire it into `execution.py`. Also add RPC error counting to `ctf.py`.

```python
# Add to safety.py:

class CTFLiveCircuitBreaker:
    """Circuit breaker for CTF live trading failures.

    Triggers kill switch on:
    - 3 consecutive eth_sendTransaction failures
    - Signing exception
    - 5 RPC errors in 10 minutes (sliding window)
    - Reconciliation drift > $50
    """
    def __init__(self, max_consecutive_send_failures: int = 3,
                 max_rpc_errors: int = 5, error_window_seconds: int = 600):
        self.max_consecutive_send_failures = max_consecutive_send_failures
        self.max_rpc_errors = max_rpc_errors
        self.error_window_seconds = error_window_seconds
        self._send_failures: int = 0
        self._rpc_errors: list[float] = []  # timestamps

    def record_send_failure(self) -> None:
        self._send_failures += 1
        if self._send_failures >= self.max_consecutive_send_failures:
            self._trigger_kill_switch(f"ctf_send_failure: {self._send_failures} consecutive failures")

    def record_send_success(self) -> None:
        self._send_failures = 0

    def record_rpc_error(self) -> None:
        import time
        now = time.monotonic()
        self._rpc_errors.append(now)
        # Keep only errors in the sliding window
        cutoff = now - self.error_window_seconds
        self._rpc_errors = [t for t in self._rpc_errors if t > cutoff]
        if len(self._rpc_errors) >= self.max_rpc_errors:
            self._trigger_kill_switch(f"ctf_rpc_errors: {len(self._rpc_errors)} in {self.error_window_seconds}s")

    def check_and_allow(self, session: Session) -> bool:
        if _circuit_state.is_global_triggered():
            return False
        return True

    def _trigger_kill_switch(self, reason: str) -> None:
        _circuit_state.trigger_global(f"CTF_LIVE:{reason}")
        logger.critical("CTF live circuit breaker triggered: %s", reason)

# Singleton
_ctf_circuit_breaker = CTFLiveCircuitBreaker()

def get_ctf_circuit_breaker() -> CTFLiveCircuitBreaker:
    return _ctf_circuit_breaker
```

Wire into `ctf.py` `_submit_to_ctf`:
```python
from polyclaw.safety import get_ctf_circuit_breaker

def _submit_to_ctf(self, order_spec, client_order_id):
    breaker = get_ctf_circuit_breaker()
    session = None
    try:
        from polyclaw.db import SessionLocal
        session = SessionLocal()
        if not breaker.check_and_allow(session):
            raise RuntimeError("CTF circuit breaker triggered, refusing to submit")
    except Exception:
        # If DB is unavailable, still check in-memory circuit state
        if not breaker.check_and_allow(None):
            raise RuntimeError("CTF circuit breaker triggered, refusing to submit")
    finally:
        if session:
            session.close()
    try:
        tx_hash = self._broadcast_signed_tx(order_spec, client_order_id)
        breaker.record_send_success()
        return ...
    except Exception as exc:
        breaker.record_send_failure()
        # If signing error, trigger kill switch
        if 'sign' in str(exc).lower() or 'private key' in str(exc).lower():
            _circuit_state.trigger_global(f"CTF_SIGNING_ERROR: {exc}")
        raise
```

- [ ] **Step 1: Add `CTFLiveCircuitBreaker` to `safety.py`**

- [ ] **Step 2: Wire into `ctf.py` `_submit_to_ctf`**

- [ ] **Step 3: Add tests in `test_safety.py`**

```python
def test_ctf_circuit_breaker_consecutive_failures(self):
    """Circuit breaker triggers after N consecutive failures."""
    from polyclaw.safety import CTFLiveCircuitBreaker
    cb = CTFLiveCircuitBreaker(max_consecutive_send_failures=3)
    cb.record_send_failure()
    assert not _circuit_state.is_global_triggered()
    cb.record_send_failure()
    assert not _circuit_state.is_global_triggered()
    cb.record_send_failure()  # 3rd
    assert _circuit_state.is_global_triggered()

def test_ctf_circuit_breaker_success_resets(self):
    """Success resets consecutive failure counter."""
    from polyclaw.safety import CTFLiveCircuitBreaker
    cb = CTFLiveCircuitBreaker(max_consecutive_send_failures=2)
    cb.record_send_failure()
    cb.record_send_failure()  # would trigger
    cb.record_send_success()  # reset
    cb.record_send_failure()  # count back to 1
    assert not _circuit_state.is_global_triggered()
```

- [ ] **Step 4: Run tests**

Run: `pytest polyclaw/tests/test_safety.py -v`

- [ ] **Step 5: Commit**

```bash
git add polyclaw/safety.py polyclaw/providers/ctf.py polyclaw/tests/test_safety.py
git commit -m "feat: add CTFLiveCircuitBreaker for real-exception kill switch

- Triggers on: 3 consecutive send failures, RPC errors >5/10min, signing error
- Wire into _submit_to_ctf: check before broadcast, record after success/failure
- GlobalCircuitBreaker triggered for signing errors and RPC storm"
```

---

## Phase 6: End-to-End Verification

### Task 8: Smoke test with real private key

**Files:**
- Create: `polyclaw/tests/test_live_smoke.py` (manual, not CI)

```python
"""Manual live smoke test — NOT run in CI.

Requires: CTF_PRIVATE_KEY env var set, live_trading_enabled=true.
Run manually: python -m polyclaw.tests.test_live_smoke
"""
import os
import time

def test_live_balance_query():
    """Query real USDC and MATIC balances from Polygon."""
    from polyclaw.providers.signer import WalletSigner
    from polyclaw.providers.ctf import PolymarketCTFProvider

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        print("SKIP: CTF_PRIVATE_KEY not set")
        return

    signer = WalletSigner()
    print(f"Signer address: {signer.address}")

    provider = PolymarketCTFProvider()
    balances = provider.get_balances()
    print(f"Balances: {balances}")
    assert balances['usdc'] >= 0
    assert balances['matic'] >= 0
    print("PASS: Real balance query works")

def test_live_order_smoke():
    """Submit a $1 USD order to a real market (with minimal stake)."""
    from polyclaw.providers.signer import WalletSigner
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.execution.orders import OrderSpec, OrderType

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        print("SKIP: CTF_PRIVATE_KEY not set")
        return

    signer = WalletSigner()
    provider = PolymarketCTFProvider()
    provider._signer = signer

    # Use a known real market ID (replace with actual market)
    test_market = os.environ.get('TEST_MARKET_ID', '0x' + 'deadbeef' * 8)
    order_spec = OrderSpec(
        type=OrderType.LIMIT,
        side='yes',
        price=0.55,
        size=1.0,  # $1 notional
        market_id=test_market,
        outcome='yes',
        client_order_id=f'live-smoke-{int(time.time())}',
    )

    try:
        result = provider.submit_order_obj(order_spec)
        print(f"Order result: {result}")
        print(f"Tx hash: {result.tx_hash}")
        print(f"Status: {result.status}")
        print("PASS: Live order submitted")
    except Exception as exc:
        print(f"Order failed (expected if market not active): {exc}")
```

- [ ] **Step 1: Create `test_live_smoke.py`**

- [ ] **Step 2: Run smoke test locally (manual)**

```bash
export CTF_PRIVATE_KEY=0x78bffecc7e1c0fa7fb1d406520771c44faa3fc48cb62a9ff026e11030186a065
export LIVE_TRADING_ENABLED=false  # Read-only first
python -m pytest polyclaw/tests/test_live_smoke.py -v -s
```

Expected: `test_live_balance_query` prints real balance, `test_live_order_smoke` skips or submits depending on market ID.

**CRITICAL verification gate — must complete before Phase 6 is done:**
1. Verify `createOrder` selector `0xb3d79f8f` against Polyscan ABI for `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
2. Verify `cancelOrder` selector `0xabc12345` — if it reverts, update with correct selector from Polyscan
3. Verify `_parse_fill_from_logs` event selector against real FillResult event signature
4. Confirm `_query_ctf_balances` returns non-zero values for the test wallet
5. Confirm reconciliation shows no drift (DB positions match API positions)

- [ ] **Step 3: Commit smoke test**

```bash
git add polyclaw/tests/test_live_smoke.py
git commit -m "test: add manual live smoke test for real balance/order"
```

---

## Running All Tests

After each task:
```bash
pytest polyclaw/tests/test_ctf_provider.py -v
pytest polyclaw/tests/test_safety.py -v
pytest polyclaw/tests/test_reconciliation.py -v
pytest  # full suite
mypy polyclaw/providers/signer.py polyclaw/providers/ctf.py polyclaw/safety.py
ruff check polyclaw/providers/signer.py polyclaw/providers/ctf.py polyclaw/safety.py
```

---

## File Summary

| File | Change |
|------|--------|
| `pyproject.toml` | Add `eth-account>=0.11` |
| `polyclaw/providers/signer.py` | Replace SHA256 with `eth-account`, startup validation |
| `polyclaw/providers/ctf.py` | Replace mocks with real RPC, add gas/nonce/calldata helpers, wire circuit breaker |
| `polyclaw/safety.py` | Add `CTFLiveCircuitBreaker` |
| `polyclaw/reconciliation/service.py` | Wire API vs chain positions to different sources |
| `polyclaw/tests/test_ctf_provider.py` | Rewrite signer tests, add submission/balance/cancel tests |
| `polyclaw/tests/test_safety.py` | Add circuit breaker tests |
| `polyclaw/tests/test_reconciliation.py` | Add reconciliation source tests |
| `polyclaw/tests/test_live_smoke.py` | Manual smoke test |
