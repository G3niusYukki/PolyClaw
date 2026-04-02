from datetime import timedelta

import pytest

from polyclaw.strategies.liquidity_momentum import (
    LiquidityMomentumConfig,
    LiquidityMomentumStrategy,
)
from polyclaw.strategies.registry import StrategyRegistry
from polyclaw.timeutils import utcnow


def test_liquidity_momentum_properties():
    strat = LiquidityMomentumStrategy()
    assert strat.strategy_id == 'liquidity_momentum'
    assert strat.name == 'Liquidity Momentum'
    assert strat.version == '1.0.0'
    assert strat.enabled is True


def test_liquidity_momentum_validate():
    strat = LiquidityMomentumStrategy()
    assert strat.validate() is True

    bad_config = LiquidityMomentumConfig(momentum_threshold=-1.0)
    bad_strat = LiquidityMomentumStrategy(config=bad_config)
    assert bad_strat.validate() is False


def test_liquidity_momentum_compute_features(sample_market):
    strat = LiquidityMomentumStrategy()
    features = strat.compute_features(sample_market)

    assert 'volume_surge_ratio' in features
    assert 'liquidity_depth' in features
    assert 'price_momentum_24h' in features
    assert 'spread_percentile' in features
    assert 'momentum_score' in features

    # volume_surge_ratio = 7000 / 25000
    assert features['volume_surge_ratio'] == pytest.approx(0.28, rel=0.01)
    # liquidity_depth = 25000 (>= 10000 tier)
    assert features['liquidity_depth'] == 25000.0
    # price_momentum = price_deviation * (1 + volume_ratio)
    # = abs(0.55 - 0.5)*2 * (1 + 7000/25000) = 0.1 * 1.28 = 0.128
    assert features['price_momentum_24h'] == pytest.approx(0.128, rel=0.01)
    assert features['spread_percentile'] == 100.0


def test_liquidity_momentum_low_liquidity():
    strat = LiquidityMomentumStrategy()

    # Low liquidity market (in 1000-3000 tier)
    now = utcnow()
    from polyclaw.domain import MarketSnapshot
    m = MarketSnapshot(
        market_id='low-liQ',
        title='Will X happen?',
        description='',
        yes_price=0.55,
        no_price=0.48,
        spread_bps=600,
        liquidity_usd=1500,
        volume_24h_usd=200,
        category='novelty',
        event_key='test',
        closes_at=now + timedelta(days=120),
        fetched_at=now,
    )
    features = strat.compute_features(m)

    # liquidity_depth = 1500 * 0.3 = 450 (in 1000-3000 tier, below min 3000)
    assert features['liquidity_depth'] == pytest.approx(450.0, rel=0.01)
    assert features['volume_surge_ratio'] == pytest.approx(200 / 1500, rel=0.01)


def test_liquidity_momentum_no_signal_without_volume_surge():
    strat = LiquidityMomentumStrategy()

    now = utcnow()
    from polyclaw.domain import MarketSnapshot
    m = MarketSnapshot(
        market_id='no-volume',
        title='Will X happen?',
        description='',
        yes_price=0.60,
        no_price=0.42,
        spread_bps=100,
        liquidity_usd=25000,
        volume_24h_usd=500,  # Low volume
        category='news',
        event_key='test',
        closes_at=now + timedelta(days=10),
        fetched_at=now,
    )
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)
    # volume_surge = 500/25000 = 0.02 < min 0.05
    assert signal is None


def test_liquidity_momentum_generates_yes_signal():
    strat = LiquidityMomentumStrategy()

    now = utcnow()
    from polyclaw.domain import MarketSnapshot
    m = MarketSnapshot(
        market_id='momentum-yes',
        title='Will Fed cut rates?',
        description='',
        yes_price=0.62,
        no_price=0.40,
        spread_bps=80,
        liquidity_usd=30000,
        volume_24h_usd=10000,
        category='macro',
        event_key='fed-cut',
        closes_at=now + timedelta(days=5),
        fetched_at=now,
    )
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)

    assert signal is not None
    assert signal.strategy_id == 'liquidity_momentum'
    assert signal.side.value == 'yes'
    assert signal.confidence > 0.5
    assert signal.edge_bps >= 700


def test_liquidity_momentum_generates_no_signal():
    strat = LiquidityMomentumStrategy()

    now = utcnow()
    from polyclaw.domain import MarketSnapshot
    m = MarketSnapshot(
        market_id='momentum-no',
        title='Will candidate win?',
        description='',
        yes_price=0.60,
        no_price=0.42,
        spread_bps=80,
        liquidity_usd=30000,
        volume_24h_usd=6000,
        category='politics',
        event_key='election',
        closes_at=now + timedelta(days=5),
        fetched_at=now,
    )
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)

    assert signal is not None
    assert signal.side.value == 'yes'
    assert signal.edge_bps >= 700


def test_liquidity_momentum_rejects_wide_spread():
    strat = LiquidityMomentumStrategy()

    now = utcnow()
    from polyclaw.domain import MarketSnapshot
    m = MarketSnapshot(
        market_id='wide-spread',
        title='Will Fed cut rates?',
        description='',
        yes_price=0.62,
        no_price=0.40,
        spread_bps=600,
        liquidity_usd=30000,
        volume_24h_usd=10000,
        category='macro',
        event_key='fed-cut',
        closes_at=now + timedelta(days=5),
        fetched_at=now,
    )
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)
    assert signal is None


def test_liquidity_momentum_registry_integration():
    StrategyRegistry.reset()
    strat = LiquidityMomentumStrategy()
    registry = StrategyRegistry()
    registry.register(strat)

    retrieved = registry.get('liquidity_momentum')
    assert retrieved is strat
    assert isinstance(retrieved, LiquidityMomentumStrategy)


def test_liquidity_momentum_custom_config():
    config = LiquidityMomentumConfig(
        max_position_pct=5.0,
        momentum_threshold=0.5,
        volume_surge_min=0.10,
    )
    strat = LiquidityMomentumStrategy(config=config)
    assert strat.config.max_position_pct == 5.0
    assert strat.validate() is True
