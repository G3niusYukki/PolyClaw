"""Wallet signing utilities for CTF transactions.

Provides a WalletSigner class that signs blockchain transactions using
a private key from AWS Secrets Manager or an environment variable.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

from polyclaw.secrets import secrets_manager


class WalletSigner:
    """
    Signs blockchain transactions using a private key.

    Supports retrieval from AWS Secrets Manager with fallback to environment variable.
    Currently returns a mock signature; real implementation would use eth_keys or web3.
    """

    def __init__(self, private_key: str | None = None):
        """
        Initialize the signer.

        Args:
            private_key: Optional private key override. If not provided, retrieves
                from AWS Secrets Manager or CTF_PRIVATE_KEY environment variable.
        """
        if private_key:
            self._private_key = private_key
        else:
            self._private_key = secrets_manager.get_ctf_private_key()

    def sign_transaction(self, tx_data: dict[str, Any]) -> str:
        """
        Sign a transaction and return the hex signature.

        Args:
            tx_data: A dictionary containing transaction data (to, value, data, etc.).

        Returns:
            The hex-encoded signature string.

        Note:
            This is a mock implementation. Real implementation would:
            1. Serialize tx_data into a transaction hash
            2. Sign with ECDSA using the private key
            3. Return the signature (r, s, v components)
        """
        if not self._private_key:
            # Return a mock signature for testing/development
            return '0xmock_signature_' + hashlib.sha256(
                str(tx_data).encode()
            ).hexdigest()[:64]

        # Mock: compute a deterministic "signature" from tx_data and private key
        # In production, use eth_keys.PrivateKey or web3.eth.account
        tx_bytes = str(tx_data).encode() + self._private_key.encode()
        sig = hashlib.sha256(tx_bytes).hexdigest()
        return '0x' + sig

    def sign_message(self, message: str) -> str:
        """
        Sign a message string.

        Args:
            message: The message to sign.

        Returns:
            The hex-encoded signature.
        """
        if not self._private_key:
            return '0xmock_sig_' + hashlib.sha256(message.encode()).hexdigest()[:64]
        msg_bytes = message.encode() + self._private_key.encode()
        sig = hashlib.sha256(msg_bytes).hexdigest()
        return '0x' + sig

    @property
    def address(self) -> str:
        """
        Derive the Ethereum address from the private key.

        Returns:
            The address as a 0x-prefixed hex string (mock).

        Note:
            Mock returns a deterministic address derived from the private key.
            Real implementation would use eth_keys or web3.
        """
        if not self._private_key:
            return '0x' + '0' * 40
        key_hash = hashlib.sha256(self._private_key.encode()).hexdigest()
        return '0x' + key_hash[-40:]


# Module-level singleton
_signer_instance: WalletSigner | None = None


def get_signer() -> WalletSigner:
    """Get or create the module-level WalletSigner singleton."""
    global _signer_instance
    if _signer_instance is None:
        _signer_instance = WalletSigner()
    return _signer_instance
