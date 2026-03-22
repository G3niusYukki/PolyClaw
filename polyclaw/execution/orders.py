"""Order type definitions and specifications."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderType(str, Enum):
    """Order execution types supported by the CTF provider."""
    LIMIT = 'limit'        # Submit at specified price, may not fill immediately
    IOC = 'ioc'            # Immediate-or-cancel: fill immediately or cancel
    POST_ONLY = 'post_only'  # Post to book without taking liquidity; cancel if would take
    MARKET = 'market'      # Execute at best available price


@dataclass
class OrderSpec:
    """
    Specification for a CTF order.

    This is a pure data class that describes how an order should be submitted,
    independent of the ORM model.
    """
    type: OrderType
    side: str  # 'yes' or 'no'
    price: float  # 0.0 to 1.0 (probability)
    size: float  # quantity of conditional tokens
    market_id: str
    outcome: str = 'yes'  # 'yes' or 'no' — the outcome being bet on
    client_order_id: str = ''
    min_fill_size: float = 0.0  # minimum size to fill for this order

    def __post_init__(self):
        if not 0.0 < self.price <= 1.0:
            raise ValueError(f"Order price must be in (0.0, 1.0], got {self.price}")
        if self.size <= 0:
            raise ValueError(f"Order size must be positive, got {self.size}")
        if self.side not in ('yes', 'no'):
            raise ValueError(f"Order side must be 'yes' or 'no', got {self.side}")

    @property
    def notional_usd(self) -> float:
        """Estimated notional value in USD (price * size)."""
        return self.price * self.size

    def to_ctf_payload(self, contract_address: str, signer_address: str) -> dict:
        """
        Build the CTF contract call payload for this order.

        Args:
            contract_address: The CTF contract address on Polygon.
            signer_address: The wallet address submitting the order.

        Returns:
            A dict suitable for signing and submitting as a JSON-RPC call.
        """
        from polyclaw.providers.signer import get_signer
        import uuid

        # Determine if this is a buy or sell based on side
        buy_amount = int(self.size * 1e6) if self.side == 'yes' else 0
        sell_amount = int(self.size * 1e6) if self.side == 'no' else 0

        # Market orders use mid price, others use specified price
        execution_price = self.price

        return {
            'method': 'eth_sendTransaction',
            'params': [{
                'to': contract_address,
                'from': signer_address,
                'data': self._build_call_data(buy_amount, sell_amount, execution_price),
                'value': hex(int(self.notional_usd * 1e6)),  # value in micro-USDC
                'gas': hex(500000),
            }],
            'client_order_id': self.client_order_id or f"ctf-{uuid.uuid4().hex[:16]}",
            'order_type': self.type.value,
            'market_id': self.market_id,
            'outcome': self.outcome,
        }

    def _build_call_data(self, buy_amount: int, sell_amount: int, price: float) -> str:
        """
        Build the ABI-encoded call data for the CTF contract.

        This is a mock implementation. Real implementation would use
        the CTF ABI and proper encoding.
        """
        price_wei = int(price * 1e6)  # CTF uses 6 decimal precision
        return (
            f"0x{self.side.encode().hex()}"  # mock: just encode side
            f"{buy_amount:064x}"              # 32-byte buy amount
            f"{sell_amount:064x}"             # 32-byte sell amount
            f"{price_wei:064x}"              # 32-byte price
        )
