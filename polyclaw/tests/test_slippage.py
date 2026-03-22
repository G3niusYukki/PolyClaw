"""Tests for the slippage model."""


from polyclaw.backtest.slippage import SlippageEstimate, SlippageModel


class TestSlippageModel:
    def setup_method(self) -> None:
        self.model = SlippageModel()

    def test_empty_order_book(self):
        result = self.model.estimate_slippage(100.0, 'yes', [])
        assert result.can_fill is False
        assert result.reason == 'empty_order_book'

    def test_zero_order_size(self):
        levels = [{'price': 0.5, 'size': 100}]
        result = self.model.estimate_slippage(0.0, 'yes', levels)
        assert result.can_fill is False
        assert result.reason == 'zero_order_size'

    def test_insufficient_liquidity_single_level(self):
        levels = [{'price': 0.5, 'size': 10}]  # Only $5 worth at this price
        result = self.model.estimate_slippage(100.0, 'yes', levels)
        assert result.can_fill is False
        assert result.reason == 'insufficient_liquidity'

    def test_full_fill_single_level(self):
        levels = [{'price': 0.5, 'size': 100}]  # $50 worth
        result = self.model.estimate_slippage(30.0, 'yes', levels)
        assert result.can_fill is True
        assert result.levels_consumed == 1
        assert result.avg_fill_price == 0.5
        assert result.slippage_pct == 0.0
        assert result.reason is None

    def test_multi_level_fill(self):
        levels = [
            {'price': 0.50, 'size': 50},   # $25 at best price
            {'price': 0.51, 'size': 50},   # $25.50 at next level
            {'price': 0.52, 'size': 50},   # $26 at next level
        ]
        # Order for $50 — should consume first level fully ($25) + part of second ($25)
        result = self.model.estimate_slippage(50.0, 'yes', levels)
        assert result.can_fill is True
        assert result.levels_consumed == 2
        assert result.avg_fill_price > 0.50
        assert result.slippage_pct > 0

    def test_no_valid_price(self):
        levels = [{'price': 0.0, 'size': 100}, {'price': -0.1, 'size': 50}]
        result = self.model.estimate_slippage(50.0, 'yes', levels)
        assert result.can_fill is False
        assert result.reason == 'no_valid_price'

    def test_exact_fill_at_multiple_levels(self):
        levels = [
            {'price': 0.50, 'size': 20},   # $10
            {'price': 0.51, 'size': 30},   # $15.30
            {'price': 0.52, 'size': 50},   # $26
        ]
        result = self.model.estimate_slippage(25.30, 'yes', levels)
        assert result.can_fill is True
        assert result.levels_consumed == 2
        assert abs(result.avg_fill_price - 0.505) < 0.01

    def test_slippage_increases_with_order_size(self):
        # Levels in ascending order: for YES (consume lowest first), a larger
        # order walks further into the book, incurring more slippage.
        levels = [
            {'price': 0.50, 'size': 50},
            {'price': 0.52, 'size': 50},
            {'price': 0.54, 'size': 50},
            {'price': 0.56, 'size': 50},
        ]

        small = self.model.estimate_slippage(10.0, 'yes', levels)
        large = self.model.estimate_slippage(50.0, 'yes', levels)

        assert small.can_fill is True
        assert large.can_fill is True
        assert small.slippage_pct == 0.0  # fills at best price
        assert large.slippage_pct > 0  # walks into book, incurs slippage

    def test_no_size_levels_skipped(self):
        levels = [
            {'price': 0.50, 'size': 0},     # Empty level
            {'price': 0.51, 'size': 100},
        ]
        result = self.model.estimate_slippage(20.0, 'yes', levels)
        assert result.can_fill is True
        assert result.avg_fill_price == 0.51

    def test_slippage_estimate_dataclass(self):
        est = SlippageEstimate(
            can_fill=True,
            avg_fill_price=0.512,
            slippage_pct=0.024,
            levels_consumed=2,
            reason=None,
        )
        assert est.can_fill is True
        assert est.avg_fill_price == 0.512
        assert est.slippage_pct == 0.024
        assert est.levels_consumed == 2
        assert est.reason is None

    def test_side_no_order(self):
        levels = [
            {'price': 0.49, 'size': 100},
            {'price': 0.48, 'size': 100},
        ]
        result = self.model.estimate_slippage(30.0, 'no', levels)
        assert result.can_fill is True
        # For NO orders, best price is the highest (0.49) and we consume from highest first.
        # Since the $30 order only partially consumes the $49 first level, slippage is 0.
        assert result.avg_fill_price == 0.49
        assert result.slippage_pct == 0.0
