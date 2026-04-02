"""Tests for the Smart Money strategy."""

from unittest.mock import MagicMock

import pytest

from polyclaw.domain import MarketSnapshot
from polyclaw.llm.parser import LLMProbabilityEstimate
from polyclaw.strategies.base import Side
from polyclaw.strategies.smart_money import SmartMoneyStrategy
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


def _make_estimate(prob_yes=0.80, confidence=0.85):
    return LLMProbabilityEstimate(
        market_id='test-mkt',
        estimated_probability_yes=prob_yes,
        confidence=confidence,
        reasoning='Strong evidence.',
        key_factors=['factor_a'],
        model='gpt-4o',
        raw_response='{}',
    )


class TestSmartMoneyStrategy:
    def test_strategy_properties(self):
        strat = SmartMoneyStrategy()
        assert strat.strategy_id == 'smart_money'
        assert strat.name == 'Smart Money'

    def test_signal_with_aligned_whale(self):
        strat = SmartMoneyStrategy()
        market = _make_market(yes_price=0.50)
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.85),
            'onchain_signals': [
                {'type': 'whale_position', 'direction': 'yes', 'magnitude': 0.8},
                {'type': 'whale_position', 'direction': 'yes', 'magnitude': 0.6},
            ],
        }
        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.YES
        assert signal.confidence > 0.85

    def test_no_signal_on_direction_mismatch(self):
        strat = SmartMoneyStrategy()
        market = _make_market(yes_price=0.50)
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80),
            'onchain_signals': [
                {'type': 'whale_position', 'direction': 'no', 'magnitude': 0.9},
            ],
        }
        assert strat.generate_signals(market, features) is None

    def test_no_signal_without_llm_estimate(self):
        strat = SmartMoneyStrategy()
        assert strat.generate_signals(_make_market(), {'llm_estimate': None, 'onchain_signals': []}) is None

    def test_no_signal_without_onchain_data(self):
        strat = SmartMoneyStrategy()
        features = {'llm_estimate': _make_estimate(), 'onchain_signals': []}
        assert strat.generate_signals(_make_market(), features) is None

    def test_no_signal_with_low_confidence(self):
        strat = SmartMoneyStrategy()
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.30),
            'onchain_signals': [{'type': 'whale', 'direction': 'yes', 'magnitude': 0.8}],
        }
        assert strat.generate_signals(_make_market(yes_price=0.50), features) is None

    def test_no_signal_insufficient_edge(self):
        strat = SmartMoneyStrategy()
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.52, confidence=0.85),
            'onchain_signals': [{'type': 'whale', 'direction': 'yes', 'magnitude': 0.8}],
        }
        assert strat.generate_signals(_make_market(yes_price=0.50), features) is None

    def test_signal_no_direction(self):
        strat = SmartMoneyStrategy()
        market = _make_market(yes_price=0.80)
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.20, confidence=0.85),
            'onchain_signals': [{'type': 'whale', 'direction': 'no', 'magnitude': 0.7}],
        }
        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.NO

    def test_multiple_signals_boost_confidence(self):
        strat = SmartMoneyStrategy()
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.80),
            'onchain_signals': [
                {'type': 'whale_position', 'direction': 'yes', 'magnitude': 0.8},
                {'type': 'tracked_wallet', 'direction': 'yes', 'magnitude': 0.6},
                {'type': 'unusual_activity', 'direction': 'yes', 'magnitude': 0.7},
            ],
        }
        signal = strat.generate_signals(_make_market(yes_price=0.50), features)
        assert signal is not None
        assert signal.confidence > 0.80 + 0.10

    def test_spread_filter(self):
        strat = SmartMoneyStrategy()
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80),
            'onchain_signals': [{'type': 'whale', 'direction': 'yes', 'magnitude': 0.8}],
        }
        assert strat.generate_signals(_make_market(yes_price=0.50, spread_bps=500), features) is None

    def test_liquidity_filter(self):
        strat = SmartMoneyStrategy()
        features = {
            'llm_estimate': _make_estimate(prob_yes=0.80),
            'onchain_signals': [{'type': 'whale', 'direction': 'yes', 'magnitude': 0.8}],
        }
        assert strat.generate_signals(_make_market(yes_price=0.50, liquidity_usd=100), features) is None
