"""Tests for slippage monitoring."""

import pytest

from polyclaw.scaling.slippage_monitor import SlippageMonitor


class TestSlippageMonitor:
    """Tests for SlippageMonitor."""

    def test_track_fill_no_slippage(self):
        monitor = SlippageMonitor()
        record = monitor.track_fill(
            expected_price=0.50,
            actual_price=0.50,
            market_id='test-market',
            size_usd=100.0,
        )
        assert record.slippage_pct == 0.0
        assert record.market_id == 'test-market'
        assert record.expected_price == 0.50
        assert record.actual_price == 0.50

    def test_track_fill_positive_slippage(self):
        monitor = SlippageMonitor()
        record = monitor.track_fill(
            expected_price=0.50,
            actual_price=0.52,
            market_id='test-market',
            size_usd=100.0,
        )
        assert record.slippage_pct == pytest.approx(0.04, rel=1e-3)  # 4%

    def test_track_fill_negative_slippage(self):
        monitor = SlippageMonitor()
        record = monitor.track_fill(
            expected_price=0.50,
            actual_price=0.48,
            market_id='test-market',
            size_usd=100.0,
        )
        assert record.slippage_pct == pytest.approx(-0.04, rel=1e-3)

    def test_get_slippage_stats_empty(self):
        monitor = SlippageMonitor()
        stats = monitor.get_slippage_stats()
        assert stats['avg_slippage_pct'] == 0.0
        assert stats['max_slippage_pct'] == 0.0
        assert stats['total_fills'] == 0
        assert stats['by_market'] == {}

    def test_get_slippage_stats_multiple_fills(self):
        monitor = SlippageMonitor()
        monitor.track_fill(0.50, 0.51, 'mkt-1', 100.0)  # 2% slip
        monitor.track_fill(0.50, 0.52, 'mkt-1', 50.0)  # 4% slip
        monitor.track_fill(0.40, 0.41, 'mkt-2', 200.0)  # 2.5% slip

        stats = monitor.get_slippage_stats()
        assert stats['total_fills'] == 3
        assert stats['avg_slippage_pct'] > 0
        assert stats['max_slippage_pct'] > 0
        assert 'mkt-1' in stats['by_market']
        assert 'mkt-2' in stats['by_market']

    def test_is_slippage_excessive_false(self):
        monitor = SlippageMonitor(avg_threshold_pct=0.01)  # 1% threshold
        monitor.track_fill(0.50, 0.505, 'mkt-1', 100.0)  # 1% slip
        assert monitor.is_slippage_excessive() is False

    def test_is_slippage_excessive_true(self):
        monitor = SlippageMonitor(avg_threshold_pct=0.005)  # 0.5% threshold
        monitor.track_fill(0.50, 0.51, 'mkt-1', 100.0)  # 2% slip
        assert monitor.is_slippage_excessive() is True

    def test_size_buckets(self):
        monitor = SlippageMonitor()
        monitor.track_fill(0.50, 0.51, 'micro', 5.0)
        monitor.track_fill(0.50, 0.51, 'small', 30.0)
        monitor.track_fill(0.50, 0.51, 'medium', 100.0)
        monitor.track_fill(0.50, 0.51, 'large', 500.0)
        monitor.track_fill(0.50, 0.51, 'xlarge', 2000.0)

        stats = monitor.get_slippage_stats()
        buckets = stats['by_size_bucket']
        assert 'micro (<=$10)' in buckets
        assert 'small ($10-$50)' in buckets
        assert 'medium ($50-$200)' in buckets
        assert 'large ($200-$1K)' in buckets
        assert 'xlarge (>$1K)' in buckets

    def test_get_excessive_slippage_markets(self):
        monitor = SlippageMonitor(avg_threshold_pct=0.01)
        monitor.track_fill(0.50, 0.52, 'good-market', 100.0)  # 4%
        monitor.track_fill(0.50, 0.501, 'bad-market', 50.0)  # 0.2%

        excessive = monitor.get_excessive_slippage_markets()
        market_ids = [mid for mid, _ in excessive]
        assert 'good-market' in market_ids
        # bad-market might or might not be in the list depending on averaging
