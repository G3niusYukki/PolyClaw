from datetime import timedelta

import pytest

from polyclaw.strategies.event_catalyst import EventCatalystConfig, EventCatalystStrategy
from polyclaw.strategies.registry import StrategyRegistry
from polyclaw.timeutils import utcnow


def test_event_catalyst_properties():
    strat = EventCatalystStrategy()
    assert strat.strategy_id == "event_catalyst"
    assert strat.name == "Event Catalyst"
    assert strat.version == "1.0.0"
    assert strat.enabled is True


def test_event_catalyst_validate():
    strat = EventCatalystStrategy()
    assert strat.validate() is True

    # Invalid config: min > max
    bad_config = EventCatalystConfig(min_days_to_resolution=30, max_days_to_resolution=3)
    bad_strat = EventCatalystStrategy(config=bad_config)
    assert bad_strat.validate() is False


def test_event_catalyst_compute_features(sample_market):
    strat = EventCatalystStrategy()
    features = strat.compute_features(sample_market)

    assert "days_to_resolution" in features
    assert "event_category" in features
    assert "volume_surge_ratio" in features
    assert "price_momentum" in features
    assert "news_sentiment" in features

    # Days to resolution should be ~10 for sample_market
    assert 9 <= features["days_to_resolution"] <= 11
    # volume_surge = 7000 / 25000
    assert features["volume_surge_ratio"] == pytest.approx(0.28, rel=0.01)
    # price_momentum = abs(0.55 - 0.5) * 2 = 0.1
    assert features["price_momentum"] == pytest.approx(0.1)


def test_event_catalyst_event_category_classification():
    strat = EventCatalystStrategy()

    # Information event keywords
    m1 = sample_market_fixture("convicted")
    assert strat._classify_event(m1.title, m1.category) == "information_event"

    m2 = sample_market_fixture("ceasefire")
    assert strat._classify_event(m2.title, m2.category) == "information_event"

    m3 = sample_market_fixture("GTA VI")
    assert strat._classify_event(m3.title, m3.category) == "novelty"

    # Use 'misc' category so 'random question' returns 'unknown' (not in fallback list)
    m4 = sample_market_fixture("random question", category="misc")
    assert strat._classify_event(m4.title, m4.category) == "unknown"


def sample_market_fixture(
    keyword: str, days: float = 10.0, yes_price: float = 0.55, category: str = "news"
):
    now = utcnow()
    from polyclaw.domain import MarketSnapshot

    return MarketSnapshot(
        market_id="test-m",
        title=f"Will {keyword} happen?",
        description="",
        yes_price=yes_price,
        no_price=0.48,
        spread_bps=100,
        liquidity_usd=25000,
        volume_24h_usd=7000,
        category=category,
        event_key="test",
        closes_at=now + timedelta(days=days),
        fetched_at=now,
    )


def test_event_catalyst_no_signal_outside_window():
    strat = EventCatalystStrategy()

    # Too close to resolution
    m = sample_market_fixture("election", days=1.0)
    signal = strat.generate_signals(m, strat.compute_features(m))
    assert signal is None

    # Too far from resolution
    m = sample_market_fixture("election", days=45.0)
    signal = strat.generate_signals(m, strat.compute_features(m))
    assert signal is None


def test_event_catalyst_generates_yes_signal():
    # Use lower min_confidence so the test market generates a signal
    config = EventCatalystConfig(min_confidence=0.25)
    strat = EventCatalystStrategy(config=config)

    # Market with market yes_price=0.55 so model_prob=0.63 gives edge >= 700 bps
    m = sample_market_fixture("win", days=10.0, yes_price=0.55)
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)

    assert signal is not None
    assert signal.strategy_id == "event_catalyst"
    assert signal.side.value == "yes"
    assert signal.confidence >= 0.25
    assert signal.edge_bps >= 700
    assert "event_category" in signal.features_used


def test_event_catalyst_generates_no_signal():
    # Use lower min_confidence so the test market generates a signal
    config = EventCatalystConfig(min_confidence=0.25)
    strat = EventCatalystStrategy(config=config)

    # Market with negative sentiment and no_price that gives edge >= 700 bps
    m = sample_market_fixture("lose", days=10.0, yes_price=0.45)
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)

    assert signal is not None
    assert signal.side.value == "no"


def test_event_catalyst_rejects_novelty_market():
    """Novelty markets (like GTA VI) should be rejected."""
    strat = EventCatalystStrategy()

    m = sample_market_fixture("GTA VI", days=10.0, yes_price=0.60)
    features = strat.compute_features(m)
    signal = strat.generate_signals(m, features)

    # Novelty markets get -0.15 conviction penalty, should be rejected
    assert signal is None, "Novelty market 'GTA VI' should be rejected due to confidence penalty"


def test_event_catalyst_no_closes_at():
    from polyclaw.domain import MarketSnapshot

    strat = EventCatalystStrategy()

    now = utcnow()
    m = MarketSnapshot(
        market_id="test-no-close",
        title="Will something happen?",
        description="",
        yes_price=0.60,
        no_price=0.42,
        spread_bps=100,
        liquidity_usd=25000,
        volume_24h_usd=7000,
        category="news",
        event_key="test",
        closes_at=None,
        fetched_at=now,
    )
    features = strat.compute_features(m)
    assert features["days_to_resolution"] == -1.0

    signal = strat.generate_signals(m, features)
    assert signal is None


def test_event_catalyst_registry_integration():
    """Test that EventCatalystStrategy registers correctly."""
    StrategyRegistry.reset()
    strat = EventCatalystStrategy()
    registry = StrategyRegistry()
    registry.register(strat)

    retrieved = registry.get("event_catalyst")
    assert retrieved is strat
    assert isinstance(retrieved, EventCatalystStrategy)


def test_event_catalyst_custom_config():
    config = EventCatalystConfig(
        min_days_to_resolution=1.0,
        max_days_to_resolution=60.0,
        min_confidence=0.70,
    )
    strat = EventCatalystStrategy(config=config)
    assert strat.config.min_confidence == 0.70
    assert strat.validate() is True
