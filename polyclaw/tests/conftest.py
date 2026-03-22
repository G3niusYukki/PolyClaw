from datetime import timedelta

import pytest

from polyclaw.db import Base
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.registry import StrategyRegistry
from polyclaw.timeutils import utcnow


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the strategy registry before and after each test."""
    StrategyRegistry.reset()
    yield
    StrategyRegistry.reset()


@pytest.fixture
def sample_market():
    """Create a sample market snapshot for testing."""
    now = utcnow()
    return MarketSnapshot(
        market_id='test-market-1',
        title='Will candidate A win the election?',
        description='Test market for unit tests.',
        yes_price=0.55,
        no_price=0.48,
        spread_bps=100,
        liquidity_usd=25000,
        volume_24h_usd=7000,
        category='politics',
        event_key='test-election-2026',
        closes_at=now + timedelta(days=10),
        fetched_at=now,
    )


@pytest.fixture
def low_liquidity_market():
    """Create a low-liquidity market for testing edge cases."""
    now = utcnow()
    return MarketSnapshot(
        market_id='test-market-low-liQ',
        title='Will Jesus Christ return before GTA VI?',
        description='Novelty market.',
        yes_price=0.48,
        no_price=0.52,
        spread_bps=600,
        liquidity_usd=1500,
        volume_24h_usd=200,
        category='novelty',
        event_key='novelty-1',
        closes_at=now + timedelta(days=120),
        fetched_at=now,
    )
