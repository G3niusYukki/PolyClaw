"""Manual live smoke test — NOT run in CI.

Requires: CTF_PRIVATE_KEY env var set, LIVE_TRADING_ENABLED=true.
Run manually: python -m pytest polyclaw/tests/test_live_smoke.py -v -s
"""
import os


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
    from polyclaw.providers.ctf import _CREATE_ORDER_SELECTOR, _CANCEL_SELECTOR

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
