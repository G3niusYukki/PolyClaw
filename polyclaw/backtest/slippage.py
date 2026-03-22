"""Slippage model for estimating execution quality in backtests."""

from dataclasses import dataclass


@dataclass
class SlippageEstimate:
    """Result of slippage estimation for an order."""
    can_fill: bool
    avg_fill_price: float
    slippage_pct: float
    levels_consumed: int
    reason: str | None


@dataclass
class OrderBookLevel:
    """A single level in an order book."""
    price: float
    size: float  # quantity available at this level


class SlippageModel:
    """Model for estimating slippage when executing an order against an order book.

    Walks through order book levels to find the average fill price for a given
    order size, accounting for adverse selection and partial fills.
    """

    def estimate_slippage(
        self,
        order_size_usd: float,
        side: str,
        order_book_levels: list[dict],
    ) -> SlippageEstimate:
        """Estimate slippage for an order by walking the order book.

        Args:
            order_size_usd: Order size in USD.
            side: 'yes' or 'no' — the direction of the order.
            order_book_levels: List of dicts with 'price' and 'size' keys,
                representing order book levels. Should be ordered from best
                to worst price (for the given side).

        Returns:
            SlippageEstimate with fill details.
        """
        if order_size_usd <= 0:
            return SlippageEstimate(
                can_fill=False,
                avg_fill_price=0.0,
                slippage_pct=0.0,
                levels_consumed=0,
                reason='zero_order_size',
            )

        if not order_book_levels:
            return SlippageEstimate(
                can_fill=False,
                avg_fill_price=0.0,
                slippage_pct=0.0,
                levels_consumed=0,
                reason='empty_order_book',
            )

        # Determine reference price (best fill price for the given side)
        if side == 'yes':
            # For YES orders (buy YES), best price is the lowest available price
            best_price = self._find_best_price(order_book_levels, prefer='low')
        else:
            # For NO orders (buy NO), best price is the highest available price
            best_price = self._find_best_price(order_book_levels, prefer='high')

        if best_price is None or best_price <= 0:
            return SlippageEstimate(
                can_fill=False,
                avg_fill_price=0.0,
                slippage_pct=0.0,
                levels_consumed=0,
                reason='no_valid_price',
            )

        # Walk order book levels to find average fill price.
        # size represents the quantity (shares) available at each price level.
        # Levels are expected in ascending price order.
        # For YES (buy YES at low price): consume from lowest price first (ascending).
        # For NO (buy NO at high price): consume from highest price first (descending).
        remaining_usd = order_size_usd
        total_spent = 0.0
        levels_consumed = 0
        filled_quantity = 0.0

        if side == 'yes':
            # Walk from lowest price (first) up to highest (last) — ascending
            walk_levels = order_book_levels
        else:
            # Walk from highest price (last) down to lowest (first) — descending by value
            walk_levels = sorted(order_book_levels, key=lambda l: l.get('price', 0.0), reverse=True)

        for i, level in enumerate(walk_levels):
            price = level.get('price', 0.0)
            quantity = level.get('size', 0.0)

            if price <= 0 or quantity <= 0:
                continue

            if remaining_usd <= 0:
                break

            level_cost = price * quantity

            if level_cost <= remaining_usd:
                # Consume this entire level
                total_spent += level_cost
                filled_quantity += quantity
                remaining_usd -= level_cost
                levels_consumed = i + 1
            else:
                # Partially consume this level
                fraction = remaining_usd / level_cost
                total_spent += remaining_usd
                filled_quantity += quantity * fraction
                levels_consumed = i + 1
                remaining_usd = 0

        if filled_quantity <= 0:
            return SlippageEstimate(
                can_fill=False,
                avg_fill_price=0.0,
                slippage_pct=0.0,
                levels_consumed=0,
                reason='insufficient_liquidity',
            )

        avg_fill_price = total_spent / filled_quantity

        # Calculate slippage relative to best price
        if best_price > 0:
            slippage_pct = abs(avg_fill_price - best_price) / best_price
        else:
            slippage_pct = 0.0

        # Check if order was fully filled
        if remaining_usd > 0:
            return SlippageEstimate(
                can_fill=False,
                avg_fill_price=avg_fill_price,
                slippage_pct=slippage_pct,
                levels_consumed=levels_consumed,
                reason='insufficient_liquidity',
            )

        return SlippageEstimate(
            can_fill=True,
            avg_fill_price=round(avg_fill_price, 6),
            slippage_pct=round(slippage_pct, 6),
            levels_consumed=levels_consumed,
            reason=None,
        )

    def _find_best_price(
        self,
        levels: list[dict],
        prefer: str = 'high',
    ) -> float | None:
        """Find the best available price from order book levels."""
        valid_prices = [
            level.get('price', 0.0)
            for level in levels
            if level.get('price', 0.0) > 0 and level.get('size', 0.0) > 0
        ]

        if not valid_prices:
            return None

        if prefer == 'high':
            return max(valid_prices)
        else:
            return min(valid_prices)
