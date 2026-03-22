import time

import pytest

from polyclaw.strategies.event_catalyst import EventCatalystStrategy
from polyclaw.strategies.features import FeatureCache, FeatureEngine
from polyclaw.strategies.liquidity_momentum import LiquidityMomentumStrategy


class TestFeatureCache:
    def test_cache_set_and_get(self):
        cache = FeatureCache(ttl_seconds=60.0)
        cache.set('key1', {'foo': 1.0})
        assert cache.get('key1') == {'foo': 1.0}

    def test_cache_miss(self):
        cache = FeatureCache(ttl_seconds=60.0)
        assert cache.get('nonexistent') is None

    def test_cache_ttl_expiry(self):
        cache = FeatureCache(ttl_seconds=0.1)
        cache.set('key1', {'foo': 1.0})
        time.sleep(0.15)
        assert cache.get('key1') is None

    def test_cache_invalidate(self):
        cache = FeatureCache(ttl_seconds=60.0)
        cache.set('key1', {'foo': 1.0})
        cache.invalidate('key1')
        assert cache.get('key1') is None

    def test_cache_clear(self):
        cache = FeatureCache(ttl_seconds=60.0)
        cache.set('key1', {'foo': 1.0})
        cache.set('key2', {'bar': 2.0})
        cache.clear()
        assert cache.get('key1') is None
        assert cache.get('key2') is None


class TestFeatureEngine:
    def test_compute_common_features(self, sample_market):
        engine = FeatureEngine()
        common = engine.compute_common_features(sample_market)

        assert 'volume_surge_ratio' in common
        assert 'liquidity_depth' in common
        assert 'price_momentum_24h' in common
        assert 'spread_percentile' in common

        assert common['volume_surge_ratio'] == pytest.approx(0.28, rel=0.01)
        assert common['liquidity_depth'] == 25000.0
        assert common['price_momentum_24h'] == pytest.approx(0.1, rel=0.01)
        assert common['spread_percentile'] == 100.0

    def test_compute_common_features_low_liquidity(self, low_liquidity_market):
        engine = FeatureEngine()
        common = engine.compute_common_features(low_liquidity_market)

        # liquidity_depth = 1500 * 0.3 = 450 (in 1000-3000 tier)
        assert common['liquidity_depth'] == pytest.approx(450.0, rel=0.01)

    def test_compute_features_across_strategies(self, sample_market):
        engine = FeatureEngine()
        strategies = [EventCatalystStrategy(), LiquidityMomentumStrategy()]

        result = engine.compute_features(sample_market, strategies)

        assert 'event_catalyst' in result
        assert 'liquidity_momentum' in result

        # Both should have common features
        for strategy_id, features in result.items():
            assert 'volume_surge_ratio' in features
            assert 'liquidity_depth' in features
            assert 'price_momentum_24h' in features
            assert 'spread_percentile' in features

        # Both should have strategy-specific features
        assert 'event_category' in result['event_catalyst']
        assert 'momentum_score' in result['liquidity_momentum']

    def test_compute_features_caching(self, sample_market):
        engine = FeatureEngine(cache_ttl_seconds=60.0)
        strategies = [EventCatalystStrategy()]

        # First call should compute
        result1 = engine.compute_features(sample_market, strategies)

        # Second call should return cached result
        result2 = engine.compute_features(sample_market, strategies)

        assert result1 == result2

    def test_compute_features_empty_strategies(self, sample_market):
        engine = FeatureEngine()
        result = engine.compute_features(sample_market, [])
        assert result == {}

    def test_invalidate_cache(self, sample_market):
        engine = FeatureEngine(cache_ttl_seconds=60.0)
        strategies = [EventCatalystStrategy()]

        engine.compute_features(sample_market, strategies)
        assert engine._cache.get(f'features:{sample_market.market_id}') is not None

        engine.invalidate_cache(sample_market.market_id)
        assert engine._cache.get(f'features:{sample_market.market_id}') is None

    def test_clear_cache(self, sample_market):
        engine = FeatureEngine(cache_ttl_seconds=60.0)
        strategies = [EventCatalystStrategy()]

        engine.compute_features(sample_market, strategies)
        engine.clear_cache()
        assert engine._cache.get(f'features:{sample_market.market_id}') is None

    def test_compute_common_features_zero_liquidity(self):
        from polyclaw.domain import MarketSnapshot
        from polyclaw.timeutils import utcnow

        m = MarketSnapshot(
            market_id='zero-liQ',
            title='Test',
            description='',
            yes_price=0.5,
            no_price=0.5,
            spread_bps=100,
            liquidity_usd=0,
            volume_24h_usd=0,
            category='test',
            event_key='test',
            closes_at=utcnow(),
            fetched_at=utcnow(),
        )
        engine = FeatureEngine()
        common = engine.compute_common_features(m)
        assert common['volume_surge_ratio'] == 0.0
        assert common['liquidity_depth'] == 0.0
