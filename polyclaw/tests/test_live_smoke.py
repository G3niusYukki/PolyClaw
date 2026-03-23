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
