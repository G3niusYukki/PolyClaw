"""Tests for price band validation."""

from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.execution.price_bands import PriceBandValidator


class TestPriceBandValidator:
    """Tests for PriceBandValidator (fat finger protection)."""

    def test_valid_order_within_band(self):
        """Order within band is accepted."""
        validator = PriceBandValidator(band_pct=2.0)
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.55,
            size=10.0,
            market_id='test',
            outcome='yes',
        )
        reference_price = 0.55  # Same as order price

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is True
        assert reason is None

    def test_order_outside_band_rejected(self):
        """Order outside band is rejected."""
        validator = PriceBandValidator(band_pct=2.0)
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.60,  # 9.1% above reference
            size=10.0,
            market_id='test',
            outcome='yes',
        )
        reference_price = 0.55

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is False
        assert reason is not None
        assert '9.09%' in reason
        assert '2.00%' in reason

    def test_exact_band_boundary_accepted(self):
        """Order exactly at band boundary is accepted."""
        validator = PriceBandValidator(band_pct=2.0)
        # 2% above reference
        reference_price = 0.50
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.51,  # Exactly 2% above
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is True

    def test_slightly_above_band_rejected(self):
        """Order slightly above band boundary is rejected."""
        validator = PriceBandValidator(band_pct=2.0)
        reference_price = 0.50
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.5201,  # 4.02% above reference (> 2%)
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is False

    def test_below_reference_price(self):
        """Order below reference price is also checked."""
        validator = PriceBandValidator(band_pct=2.0)
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='no',
            price=0.40,  # Below reference by ~27%
            size=10.0,
            market_id='test',
            outcome='no',
        )
        reference_price = 0.55

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is False

    def test_zero_reference_price_rejected(self):
        """Zero reference price is invalid."""
        validator = PriceBandValidator()
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.5,
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate(order_spec, 0.0)
        assert is_valid is False
        assert 'Invalid reference price' in reason

    def test_negative_reference_price_rejected(self):
        """Negative reference price is invalid."""
        validator = PriceBandValidator()
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.5,
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate(order_spec, -0.1)
        assert is_valid is False

    def test_custom_band_width(self):
        """Custom band width changes the threshold."""
        # 5% band should accept up to 5% deviation
        validator = PriceBandValidator(band_pct=5.0)
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.54,  # 4% above reference
            size=10.0,
            market_id='test',
            outcome='yes',
        )
        reference_price = 0.52

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is True

    def test_validate_market_order_within_slippage(self):
        """Market orders within slippage tolerance are accepted."""
        validator = PriceBandValidator()
        order_spec = OrderSpec(
            type=OrderType.MARKET,
            side='yes',
            price=0.555,  # 0.9% slippage
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate_market_order(order_spec, 0.55, max_slippage_pct=1.0)
        assert is_valid is True

    def test_validate_market_order_exceeds_slippage(self):
        """Market orders exceeding slippage tolerance are rejected."""
        validator = PriceBandValidator()
        order_spec = OrderSpec(
            type=OrderType.MARKET,
            side='yes',
            price=0.60,  # 9% slippage
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        is_valid, reason = validator.validate_market_order(order_spec, 0.55, max_slippage_pct=1.0)
        assert is_valid is False
        assert 'slippage' in reason.lower()

    def test_validate_non_market_order_uses_standard_band(self):
        """Non-market orders use standard band validation, not slippage."""
        validator = PriceBandValidator(band_pct=2.0)
        order_spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.555,
            size=10.0,
            market_id='test',
            outcome='yes',
        )

        # LIMIT orders use standard band (not slippage), so 1% deviation < 2% band
        is_valid, reason = validator.validate_market_order(order_spec, 0.55)
        assert is_valid is True

    def test_ioc_order_validation(self):
        """IOC orders also use standard band validation."""
        validator = PriceBandValidator(band_pct=1.0)
        order_spec = OrderSpec(
            type=OrderType.IOC,
            side='yes',
            price=0.56,  # 1% above reference
            size=5.0,
            market_id='test-ioc',
            outcome='yes',
        )
        reference_price = 0.555

        is_valid, reason = validator.validate(order_spec, reference_price)
        # 0.9% deviation < 1% band
        assert is_valid is True

    def test_post_only_order_validation(self):
        """POST_ONLY orders use standard band validation."""
        validator = PriceBandValidator(band_pct=2.0)
        order_spec = OrderSpec(
            type=OrderType.POST_ONLY,
            side='yes',
            price=0.555,
            size=10.0,
            market_id='test-post',
            outcome='yes',
        )
        reference_price = 0.55

        is_valid, reason = validator.validate(order_spec, reference_price)
        assert is_valid is True
