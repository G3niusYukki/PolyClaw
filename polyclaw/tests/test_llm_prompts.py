"""Tests for LLM prompt templates."""

from polyclaw.domain import MarketSnapshot
from polyclaw.llm.prompts import build_probability_prompt
from polyclaw.timeutils import utcnow


def _make_market(**overrides) -> MarketSnapshot:
    defaults: dict = {
        'market_id': 'test-1',
        'title': 'Will X happen?',
        'description': 'A test market.',
        'yes_price': 0.65,
        'no_price': 0.35,
        'spread_bps': 100,
        'liquidity_usd': 5000.0,
        'volume_24h_usd': 2000.0,
        'category': 'politics',
        'event_key': 'test-event',
        'closes_at': None,
        'fetched_at': utcnow(),
    }
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


class TestBuildProbabilityPrompt:
    def test_returns_tuple(self):
        market = _make_market()
        system, user = build_probability_prompt(market)
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_requests_json(self):
        market = _make_market()
        system, _ = build_probability_prompt(market)
        assert 'probability_yes' in system
        assert 'confidence' in system
        assert 'key_factors' in system

    def test_user_prompt_includes_market_info(self):
        market = _make_market(
            title='Will BTC reach $100k?',
            description='Bitcoin price prediction.',
            category='crypto',
        )
        _, user = build_probability_prompt(market)
        assert 'Will BTC reach $100k?' in user
        assert 'Bitcoin price prediction.' in user
        assert 'crypto' in user
        assert '0.65' in user

    def test_user_prompt_shows_unknown_close_date(self):
        market = _make_market(closes_at=None)
        _, user = build_probability_prompt(market)
        assert 'Unknown' in user

    def test_user_prompt_shows_close_date(self):
        from datetime import datetime, timezone
        closes = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        market = _make_market(closes_at=closes)
        _, user = build_probability_prompt(market)
        assert '2026-06-01' in user
