"""Price band validator for fat finger protection."""
from __future__ import annotations

import logging

from polyclaw.config import settings
from polyclaw.execution.orders import OrderSpec

logger = logging.getLogger(__name__)


class PriceBandValidator:
    """
    Validates order prices against a reference price to prevent fat finger errors.

    Rejects orders where the order price deviates from the reference price by
    more than the configured band percentage.
    """

    def __init__(self, band_pct: float | None = None):
        """
        Initialize the validator.

        Args:
            band_pct: Maximum allowed deviation from reference price, as a
                percentage (e.g., 2.0 for 2%). Defaults to the
                PRICE_BAND_PCT config value, or 2.0 if not set.
        """
        configured = getattr(settings, 'price_band_pct', None)
        self._band_pct = band_pct if band_pct is not None else (configured or 2.0)

    def validate(self, order_spec: OrderSpec, reference_price: float) -> tuple[bool, str | None]:
        """
        Validate an order's price against a reference price.

        Args:
            order_spec: The order specification to validate.
            reference_price: The reference price (e.g., current market mid price).

        Returns:
            A tuple of (is_valid, reason). If valid, reason is None.
            If invalid, reason is a human-readable explanation.
        """
        if reference_price <= 0:
            return False, f"Invalid reference price: {reference_price}"

        deviation_pct = abs(order_spec.price - reference_price) / reference_price * 100.0

        # Use a small epsilon to handle floating point precision at boundaries
        # deviation_pct <= band_pct is the acceptance condition
        if deviation_pct > self._band_pct + 1e-9:
            reason = (
                f"Order price {order_spec.price:.4f} deviates {deviation_pct:.2f}% "
                f"from reference {reference_price:.4f}, exceeds band of {self._band_pct:.2f}%"
            )
            logger.warning("Price band violation: %s", reason)
            return False, reason

        return True, None

    def validate_market_order(
        self,
        order_spec: OrderSpec,
        mid_price: float,
        max_slippage_pct: float = 1.0,
    ) -> tuple[bool, str | None]:
        """
        Validate a market order against the mid price with slippage check.

        For market orders, the order price is compared against the mid price
        to ensure the order doesn't slip too far from the expected fill price.

        Args:
            order_spec: The order specification to validate.
            mid_price: The current mid price of the market.
            max_slippage_pct: Maximum allowed slippage for market orders (default 1.0%).

        Returns:
            A tuple of (is_valid, reason). If valid, reason is None.
        """
        if order_spec.type.value != 'market':
            # For non-market orders, use standard band validation
            return self.validate(order_spec, mid_price)

        if mid_price <= 0:
            return False, f"Invalid mid price: {mid_price}"

        slippage = abs(order_spec.price - mid_price) / mid_price * 100.0
        if slippage > max_slippage_pct:
            reason = (
                f"Market order slippage {slippage:.2f}% exceeds maximum "
                f"{max_slippage_pct:.2f}% (mid={mid_price:.4f}, order_price={order_spec.price:.4f})"
            )
            logger.warning("Market order slippage violation: %s", reason)
            return False, reason

        return True, None
