"""Tests for the LLM Probability strategy."""

from unittest.mock import MagicMock, patch

import pytest

from polyclaw.domain import MarketSnapshot
from polyclaw.llm.parser import LLMProbabilityEstimate
from polyclaw.strategies.base import Side
from polyclaw.strategies.llm_probability import LLMProbabilityStrategy
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


def _make_estimate(prob_yes=0.8, confidence=0.85, market_id='test-mkt'):
    return LLMProbabilityEstimate(
        market_id=market_id,
        estimated_probability_yes=prob_yes,
        confidence=confidence,
        reasoning='Strong evidence suggests this will happen.',
        key_factors=['factor_a', 'factor_b'],
        model='gpt-4o',
        raw_response='{}',
    )


class TestLLMProbabilityStrategy:
    def test_strategy_properties(self):
        strat = LLMProbabilityStrategy()
        assert strat.strategy_id == 'llm_probability'
        assert strat.name == 'LLM Probability Estimation'
        assert strat.version == '1.0.0'

    def test_compute_features_returns_estimate(self):
        mock_llm = MagicMock()
        raw_resp = '{"reasoning": "test", "probability_yes": 0.75, "confidence": 0.8, "key_factors": []}'
        mock_llm.complete.return_value = raw_resp

        strat = LLMProbabilityStrategy(llm_client=mock_llm)
        market = _make_market()
        features = strat.compute_features(market)

        assert features['llm_estimate'] is not None
        assert features['llm_estimate'].estimated_probability_yes == 0.75

    def test_compute_features_returns_none_on_failure(self):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = None

        strat = LLMProbabilityStrategy(llm_client=mock_llm)
        market = _make_market()
        features = strat.compute_features(market)

        assert features['llm_estimate'] is None

    def test_generate_signal_yes_direction(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.50)
        features = {'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.85)}

        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.YES
        assert signal.edge_bps > 0

    def test_generate_signal_no_direction(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.80)
        features = {'llm_estimate': _make_estimate(prob_yes=0.30, confidence=0.80)}

        signal = strat.generate_signals(market, features)
        assert signal is not None
        assert signal.side == Side.NO

    def test_no_signal_when_no_estimate(self):
        strat = LLMProbabilityStrategy()
        market = _make_market()
        features = {'llm_estimate': None}

        signal = strat.generate_signals(market, features)
        assert signal is None

    def test_no_signal_when_low_confidence(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.50)
        features = {'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.30)}

        signal = strat.generate_signals(market, features)
        assert signal is None

    def test_no_signal_when_edge_too_small(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.50)
        # LLM says 0.52, market says 0.50 — only 200bps edge, below default min_edge_bps=700
        features = {'llm_estimate': _make_estimate(prob_yes=0.52, confidence=0.85)}

        signal = strat.generate_signals(market, features)
        assert signal is None

    def test_no_signal_when_spread_too_wide(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.50, spread_bps=500)
        features = {'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.85)}

        signal = strat.generate_signals(market, features)
        assert signal is None

    def test_no_signal_when_liquidity_too_low(self):
        strat = LLMProbabilityStrategy()
        market = _make_market(yes_price=0.50, liquidity_usd=100)
        features = {'llm_estimate': _make_estimate(prob_yes=0.80, confidence=0.85)}

        signal = strat.generate_signals(market, features)
        assert signal is None
