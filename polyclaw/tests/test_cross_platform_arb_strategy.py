"""Tests for the Cross-Platform Arbitrage strategy."""

from unittest.mock import MagicMock, patch

import pytest

from polyclaw.data.cross_platform import CrossPlatformPrice
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import Side
from polyclaw.strategies.cross_platform_arb import CrossPlatformArbStrategy
from polyclaw.timeutils import utcnow


def _make_market(yes_price=0.50, **overrides) -> MarketSnapshot:
    defaults = dict(
        market_id='test-mkt',
        title='Will X happen?',
        description='A test market.',
        yes_price=yes_price,
        no_price=1 - yes_price,
        spread_bps=100,
        liquidity_usd=5000.0,
        volume_24h_usd=2000.0,
        category='politics',
        event_key='test-event',
        closes_at=None,
        fetched_at=utcnow(),
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


class TestCrossPlatformArbStrategy:
    def test_strategy_properties(self):
        strat = CrossPlatformArbStrategy()
        assert strat.strategy_id == 'cross_platform_arb'
        assert strat.name == 'Cross-Platform Arbitrage'

    def test_signal_when_polymarket_overpriced(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=300)
        market = _make_market(yes_price=0.70)
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.50, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.48, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.49,
                'platform_count': 2,
                'platforms': ['manifold', 'metaculus'],
                'total_weight': 1.5,
            },
        }
        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.NO  # Polymarket YES is overpriced
        assert signal.edge_bps > 300

    def test_signal_when_polymarket_underpriced(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=300)
        market = _make_market(yes_price=0.30)
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.60, similarity_score=0.8),
                CrossPlatformPrice('kalshi', 'Will X?', 0.58, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.59,
                'platform_count': 2,
                'platforms': ['kalshi', 'manifold'],
                'total_weight': 1.5,
            },
        }
        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.YES  # Polymarket YES is underpriced

    def test_no_signal_without_prices(self):
        strat = CrossPlatformArbStrategy()
        features = {'cross_platform_prices': [], 'consensus': None}
        assert strat.generate_signals(_make_market(), features) is None

    def test_no_signal_without_consensus(self):
        strat = CrossPlatformArbStrategy()
        features = {
            'cross_platform_prices': [CrossPlatformPrice('manifold', 'X', 0.5)],
            'consensus': None,
        }
        assert strat.generate_signals(_make_market(), features) is None

    def test_no_signal_below_min_platforms(self):
        strat = CrossPlatformArbStrategy()
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.80, similarity_score=0.9),
            ],
            'consensus': {
                'probability_yes': 0.80,
                'platform_count': 1,
                'platforms': ['manifold'],
                'total_weight': 0.9,
            },
        }
        assert strat.generate_signals(_make_market(yes_price=0.50), features) is None

    def test_no_signal_insufficient_discrepancy(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=500)
        market = _make_market(yes_price=0.50)
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.53, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.54, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.535,
                'platform_count': 2,
                'platforms': ['manifold', 'metaculus'],
                'total_weight': 1.5,
            },
        }
        assert strat.generate_signals(market, features) is None

    def test_spread_filter(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=300)
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.30, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.28, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.29,
                'platform_count': 2,
                'platforms': ['manifold', 'metaculus'],
                'total_weight': 1.5,
            },
        }
        assert strat.generate_signals(_make_market(yes_price=0.70, spread_bps=500), features) is None

    def test_liquidity_filter(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=300)
        features = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.30, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.28, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.29,
                'platform_count': 2,
                'platforms': ['manifold', 'metaculus'],
                'total_weight': 1.5,
            },
        }
        assert strat.generate_signals(_make_market(yes_price=0.70, liquidity_usd=50), features) is None

    def test_confidence_increases_with_more_platforms(self):
        strat = CrossPlatformArbStrategy(min_discrepancy_bps=300)

        features_2 = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.35, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.33, similarity_score=0.7),
            ],
            'consensus': {
                'probability_yes': 0.34,
                'platform_count': 2,
                'platforms': ['manifold', 'metaculus'],
                'total_weight': 1.5,
            },
        }
        features_3 = {
            'cross_platform_prices': [
                CrossPlatformPrice('manifold', 'Will X?', 0.35, similarity_score=0.8),
                CrossPlatformPrice('metaculus', 'Will X?', 0.33, similarity_score=0.7),
                CrossPlatformPrice('kalshi', 'Will X?', 0.34, similarity_score=0.6),
            ],
            'consensus': {
                'probability_yes': 0.34,
                'platform_count': 3,
                'platforms': ['kalshi', 'manifold', 'metaculus'],
                'total_weight': 2.1,
            },
        }

        # Use a market where edge is moderate so confidence doesn't cap at 0.90
        signal_2 = strat.generate_signals(_make_market(yes_price=0.50), features_2)
        signal_3 = strat.generate_signals(_make_market(yes_price=0.50), features_3)
        assert signal_2 is not None
        assert signal_3 is not None
        assert signal_3.confidence > signal_2.confidence

    def test_compute_features_with_mock_fetcher(self):
        fetcher = MagicMock()
        fetcher.fetch_all_platforms.return_value = [
            CrossPlatformPrice('manifold', 'Will X?', 0.55, similarity_score=0.8),
            CrossPlatformPrice('metaculus', 'Will X?', 0.60, similarity_score=0.7),
        ]
        strat = CrossPlatformArbStrategy(fetcher=fetcher)
        market = _make_market(yes_price=0.50)
        features = strat.compute_features(market)

        assert len(features['cross_platform_prices']) == 2
        assert features['consensus'] is not None
        assert features['consensus']['platform_count'] == 2
        assert 0.5 < features['consensus']['probability_yes'] < 0.7

    def test_compute_features_handles_fetch_error(self):
        fetcher = MagicMock()
        fetcher.fetch_all_platforms.side_effect = Exception('Network error')
        strat = CrossPlatformArbStrategy(fetcher=fetcher)
        features = strat.compute_features(_make_market())
        assert features['cross_platform_prices'] == []
        assert features['consensus'] is None
