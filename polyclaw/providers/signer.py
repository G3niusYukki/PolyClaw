"""Wallet signing utilities for CTF transactions."""
from __future__ import annotations

from typing import Any

from eth_account import Account

from polyclaw.config import settings
from polyclaw.secrets import secrets_manager


class WalletSigner:
    """Signs blockchain transactions using a private key via eth-account secp256k1."""

    def __init__(self, private_key: str | None = None):
        if private_key:
            self._private_key = private_key
        else:
            self._private_key = secrets_manager.get_ctf_private_key()
        self._account = None
        if self._private_key:
            try:
                # eth-account accepts keys with or without 0x prefix
                normalized = self._private_key
                if not normalized.startswith('0x'):
                    normalized = '0x' + normalized
                self._account = Account.from_key(normalized)
            except Exception:
                self._account = None
        # Startup validation: fail if live_trading_enabled but no valid key
        if settings.live_trading_enabled and not self._private_key:
            raise ValueError("CTF_PRIVATE_KEY is required when live_trading_enabled=true. Refusing to start in mock mode.")
        if self._account is None and self._private_key:
            raise ValueError("Invalid private key format: could not derive Ethereum account")

    @property
    def address(self) -> str:
        """Return the Ethereum address derived from the private key."""
        if not self._account:
            raise ValueError("Cannot get address: no private key configured")
        return self._account.address  # type: ignore[no-any-return]

    def sign_transaction(self, tx_data: dict) -> str:
        """Sign a transaction. Returns rawTransaction.hex() for eth_sendRawTransaction."""
        if not self._account:
            raise ValueError("Cannot sign: no private key configured")
        signable = self._build_signable_tx(tx_data)
        signed = self._account.sign_transaction(signable)
        return '0x' + signed.raw_transaction.hex()  # type: ignore[no-any-return]

    def _build_signable_tx(self, tx_data: dict) -> dict:
        """Convert raw tx_data dict to eth-account signable format (EIP-1559)."""
        raw_value = tx_data.get('value', 0)
        if isinstance(raw_value, str) and raw_value.startswith('0x'):
            value = int(raw_value, 16)
        else:
            value = raw_value or 0
        signable = {
            'to': tx_data['to'],
            'data': tx_data.get('data', '0x'),
            'value': value,
            'nonce': tx_data.get('nonce', 0),
            'gas': tx_data.get('gas', 500000),
            'maxFeePerGas': tx_data.get('maxFeePerGas', 0),
            'maxPriorityFeePerGas': tx_data.get('maxPriorityFeePerGas', 0),
            'chainId': tx_data.get('chainId', 137),
            'type': 2,
        }
        # Only include 'from' if explicitly provided and matches the signing key
        tx_from = tx_data.get('from')
        if tx_from and self._account and tx_from.lower() == self._account.address.lower():
            signable['from'] = tx_from
        return signable

    def sign_message(self, message: str) -> str:
        """Sign a message string. Returns hex signature."""
        if not self._account:
            raise ValueError("Cannot sign: no private key configured")
        signed = self._account.sign_message(message)
        return signed.signature.hex()  # type: ignore[no-any-return]


# Module-level singleton
_signer_instance: WalletSigner | None = None


def get_signer() -> WalletSigner:
    """Get or create the module-level WalletSigner singleton."""
    global _signer_instance
    if _signer_instance is None:
        _signer_instance = WalletSigner()
    return _signer_instance


def reset_signer() -> None:
    """Reset the singleton. Call between tests to prevent state leakage."""
    global _signer_instance
    _signer_instance = None
