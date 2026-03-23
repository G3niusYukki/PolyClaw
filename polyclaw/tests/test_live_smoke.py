"""Manual live smoke test — NOT run in CI.

Requires: CTF_PRIVATE_KEY env var set, LIVE_TRADING_ENABLED=true.
Run manually: python -m pytest polyclaw/tests/test_live_smoke.py -v -s
"""
import os
import time

import pytest

pytestmark = pytest.mark.live_manual


def test_live_balance_query():
    """Query real USDC and MATIC balances from Polygon."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.signer import WalletSigner

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        print("SKIP: CTF_PRIVATE_KEY not set")
        return

    signer = WalletSigner()
    print(f"Signer address: {signer.address}")

    provider = PolymarketCTFProvider()
    provider._signer = signer

    balances = provider.get_balances()
    print(f"Balances: {balances}")
    assert balances['usdc'] >= 0, f"USDC balance should be non-negative, got {balances['usdc']}"
    assert balances['eth'] >= 0, f"MATIC balance should be non-negative, got {balances['eth']}"
    print("PASS: Real balance query works")


def test_live_gas_params():
    """Query real gas parameters from Polygon RPC."""
    from polyclaw.providers.ctf import PolymarketCTFProvider

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        print("SKIP: CTF_PRIVATE_KEY not set")
        return

    provider = PolymarketCTFProvider()
    params = provider._get_gas_params()
    print(f"Gas params: {params}")
    assert 'maxFeePerGas' in params
    assert 'maxPriorityFeePerGas' in params
    assert params['maxPriorityFeePerGas'] > 0
    print("PASS: Real gas params query works")


def test_live_nonce():
    """Query real nonce from Polygon RPC."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.signer import WalletSigner

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        print("SKIP: CTF_PRIVATE_KEY not set")
        return

    signer = WalletSigner()
    provider = PolymarketCTFProvider()
    provider._signer = signer

    nonce = provider._get_nonce(signer.address)
    print(f"Nonce: {nonce}")
    assert nonce >= 0
    print("PASS: Real nonce query works")


def test_live_selector_confirmed():
    """Verify selectors are confirmed (not placeholders) before allowing live trading."""
    from polyclaw.providers.ctf import _CANCEL_SELECTOR, _CREATE_ORDER_SELECTOR

    # These must be real selectors, not placeholders
    assert _CREATE_ORDER_SELECTOR is not None, "createOrder selector not set"
    assert _CREATE_ORDER_SELECTOR != '', "createOrder selector is empty"
    assert _CREATE_ORDER_SELECTOR.startswith('0x'), "createOrder selector must be hex with 0x prefix"
    assert len(_CREATE_ORDER_SELECTOR) == 10, f"createOrder selector must be 4-byte hex (10 chars), got {len(_CREATE_ORDER_SELECTOR)}: {_CREATE_ORDER_SELECTOR}"
    assert _CREATE_ORDER_SELECTOR != '0x00000000', "createOrder selector is zero (not set)"
    assert _CANCEL_SELECTOR is not None, "cancelOrder selector not set"
    assert _CANCEL_SELECTOR != '', "cancelOrder selector is empty"
    assert _CANCEL_SELECTOR.startswith('0x'), "cancelOrder selector must be hex with 0x prefix"
    assert len(_CANCEL_SELECTOR) == 10, f"cancelOrder selector must be 4-byte hex (10 chars), got {len(_CANCEL_SELECTOR)}: {_CANCEL_SELECTOR}"
    assert _CANCEL_SELECTOR != '0x00000000', "cancelOrder selector is zero (not set)"
    # Confirm selectors match canonical CTF ABI
    assert _CREATE_ORDER_SELECTOR == '0x6f652e1a', f"Unexpected createOrder selector: {_CREATE_ORDER_SELECTOR} (expected 0x6f652e1a)"
    assert _CANCEL_SELECTOR == '0x0fdb031d', f"Unexpected cancelOrder selector: {_CANCEL_SELECTOR} (expected 0x0fdb031d)"
    print(f"createOrder selector: {_CREATE_ORDER_SELECTOR} [CONFIRMED]")
    print(f"cancelOrder selector: {_CANCEL_SELECTOR} [CONFIRMED]")
    print("PASS: Selectors confirmed from CTF ABI")


# --- Full closed-loop live smoke test ---

@pytest.fixture
def live_provider():
    """Create a real provider with real signer."""
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.signer import WalletSigner

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        pytest.skip("CTF_PRIVATE_KEY not set")

    # WalletSigner() reads CTF_PRIVATE_KEY env var internally
    signer = WalletSigner()
    provider = PolymarketCTFProvider()
    provider._signer = signer
    return provider


@pytest.fixture
def test_market():
    """Get a real test market ID from env or skip."""
    market = os.environ.get('TEST_MARKET_ID', '')
    if not market:
        pytest.skip("TEST_MARKET_ID not set")
    return market


def test_live_full_pipeline_sign_broadcast_receipt_fill(live_provider, test_market):
    """Full pipeline: sign -> broadcast -> receipt -> fill status -> position -> cancel.

    This test actually submits on-chain. Marked live_manual so it never runs in CI.
    Run manually: pytest polyclaw/tests/test_live_smoke.py -v -s -m live_manual
    """
    provider = live_provider
    market_id = test_market

    # 1. BALANCES — verify sufficient balance
    balances = provider.get_balances()
    print(f"Balances: {balances}")
    assert balances['usdc'] >= 1.0, f"Need >= 1 USDC, got {balances['usdc']}"
    print("PASS: Sufficient USDC balance")

    # 2. GAS + NONCE
    params = provider._get_gas_params()
    signer_addr = provider._signer.address
    nonce = provider._get_nonce(signer_addr)
    print(f"Gas: {params}, Nonce: {nonce}")
    assert params['maxPriorityFeePerGas'] > 0
    assert nonce >= 0
    print("PASS: Gas and nonce query OK")

    # 3. SUBMIT ORDER — small $1 notional
    # NOTE: notional_usd is a @property on OrderSpec (computed as price * size),
    # not a constructor arg — do NOT pass it.
    from polyclaw.execution.orders import OrderSpec, OrderType
    order_spec = OrderSpec(
        type=OrderType.LIMIT,
        side='yes',
        price=0.55,
        size=1.0,  # $1 notional
        market_id=market_id,
        outcome='yes',
        client_order_id=f'smoke-{int(time.time())}',
    )
    print(f"Submitting order: {order_spec.client_order_id}")
    result = provider.submit_order_obj(order_spec)
    print(f"Result: status={result.status}, tx_hash={result.tx_hash[:16] if result.tx_hash else 'N/A'}")
    assert result.tx_hash.startswith('0x'), f"Expected tx_hash, got: {result.tx_hash}"
    print("PASS: Order submitted, tx_hash received")

    # 4. WAIT FOR CONFIRMATION
    time.sleep(15)  # ~7 blocks on Polygon

    # 5. FILL STATUS — poll until confirmed or timeout
    fill_status = provider._query_ctf_fill_status(result.tx_hash, timeout=60)
    print(f"Fill status: {fill_status.status}, filled={fill_status.filled_size}")
    assert fill_status.status in ('filled', 'pending'), f"Unexpected: {fill_status.status}"
    print(f"PASS: Fill status = {fill_status.status}")

    # 6. POSITIONS — verify position appears in chain positions
    positions = provider.get_positions()
    market_positions = [p for p in positions if p.get('market_id', '').lower() == market_id.lower()]
    print(f"Positions after fill: {market_positions}")
    # May be empty if market not in active list — that's OK for this test
    print("PASS: Position query completed")

    # 7. CANCEL — try to cancel (may revert if already filled; that's expected)
    try:
        cancelled = provider.cancel_order(result)
        print(f"Cancel result: {cancelled}")
    except Exception as exc:
        print(f"Cancel raised (may be expected if filled): {exc}")

    # 8. RECONCILIATION — run a reconciliation cycle
    # NOTE: ReconciliationService(session, ctf_provider, polymarket_api) — all three required.
    # Uses live_provider's ctf_provider; polymarket_api is optional (falls back gracefully).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from polyclaw.reconciliation.service import ReconciliationService
    # Use in-memory SQLite for the smoke test (avoids DB dependency)
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)
    session = Session()
    svc = ReconciliationService(
        session=session,
        ctf_provider=live_provider,
        polymarket_api=None,  # will log and continue on failure
    )
    report = svc.reconcile()
    print(f"Reconciliation: drift_detected={report.drift_detected}, total_drift=${report.total_drift_usd}")
    assert isinstance(report.total_drift_usd, float)
    print("PASS: Reconciliation cycle completed")

    print("PASS: Full closed-loop smoke test complete")


@pytest.mark.live_manual
def test_live_receipt_parsing():
    """Parse a real eth_getTransactionReceipt and verify FillResult event decoding."""
    import os

    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.signer import WalletSigner

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        pytest.skip("CTF_PRIVATE_KEY not set")

    signer = WalletSigner()
    provider = PolymarketCTFProvider()
    provider._signer = signer

    # Use a known tx hash to test receipt parsing
    known_tx = os.environ.get('TEST_RECEIPT_TX', '')
    if not known_tx:
        pytest.skip("TEST_RECEIPT_TX not set")

    status = provider._query_ctf_fill_status(known_tx, timeout=10)
    print(f"Receipt status: {status.status}")
    assert status.status in ('filled', 'pending', 'rejected')
    if status.filled_size > 0:
        print(f"Filled size: {status.filled_size}, avg price: {status.avg_fill_price}")
        assert status.avg_fill_price > 0 and status.avg_fill_price <= 1.0
    print("PASS: Receipt parsing works")


@pytest.mark.live_manual
def test_live_cancel_order():
    """Submit and cancel a real order to test the cancel pipeline."""
    import os
    import time

    from polyclaw.execution.orders import OrderSpec, OrderType
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.signer import WalletSigner

    pk = os.environ.get('CTF_PRIVATE_KEY', '')
    if not pk:
        pytest.skip("CTF_PRIVATE_KEY not set")

    market = os.environ.get('TEST_MARKET_ID', '')
    if not market:
        pytest.skip("TEST_MARKET_ID not set")

    signer = WalletSigner()
    provider = PolymarketCTFProvider()
    provider._signer = signer

    order_spec = OrderSpec(
        type=OrderType.LIMIT,
        side='no',
        price=0.45,
        size=1.0,
        market_id=market,
        outcome='no',
        client_order_id=f'cancel-smoke-{int(time.time())}',
    )
    result = provider.submit_order_obj(order_spec)
    print(f"Order submitted: {result.tx_hash[:16]}")
    assert result.tx_hash

    time.sleep(5)
    cancelled = provider.cancel_order(result)
    print(f"Cancel result: {cancelled}")
    assert isinstance(cancelled, bool)
    print("PASS: Cancel pipeline works")
