import time
from threading import Lock

from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy


class FeatureCache:
    """Simple TTL-based feature cache."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds

    def get(self, key: str) -> dict | None:
        with self._lock:
            if key not in self._cache:
                return None
            timestamp, value = self._cache[key]
            if time.time() - timestamp > self._ttl:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._cache[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


class FeatureEngine:
    """Computes features for markets across all strategies, with optional caching."""

    def __init__(self, cache_ttl_seconds: float = 60.0) -> None:
        self._cache = FeatureCache(cache_ttl_seconds)

    def compute_features(
        self, market: MarketSnapshot, strategies: list[BaseStrategy]
    ) -> dict[str, dict]:
        """Compute all features for a market across all strategies.

        First computes common features, then delegates to each strategy for
        strategy-specific features. Results are cached per market_id.

        Args:
            market: The market snapshot to analyze.
            strategies: List of strategies that will consume the features.

        Returns:
            Dictionary mapping strategy_id -> {common_features + strategy_features}.
        """
        cache_key = f'features:{market.market_id}'
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        common = self.compute_common_features(market)
        result: dict[str, dict] = {}

        for strategy in strategies:
            strategy_features = strategy.compute_features(market)
            result[strategy.strategy_id] = {
                **common,
                **strategy_features,
            }

        self._cache.set(cache_key, result)
        return result

    def compute_common_features(self, market: MarketSnapshot) -> dict:
        """Compute features shared across all strategies.

        Includes volume surge, liquidity depth, price momentum, and spread quality.

        Args:
            market: The market snapshot to analyze.

        Returns:
            Dictionary of common feature name -> value.
        """
        # Volume surge ratio
        volume_surge_ratio = (
            market.volume_24h_usd / market.liquidity_usd
            if market.liquidity_usd > 0
            else 0.0
        )

        # Liquidity depth (similar to ranking logic)
        if market.liquidity_usd >= 10000:
            liquidity_depth = market.liquidity_usd
        elif market.liquidity_usd >= 3000:
            liquidity_depth = market.liquidity_usd * 0.7
        elif market.liquidity_usd >= 1000:
            liquidity_depth = market.liquidity_usd * 0.3
        else:
            liquidity_depth = 0.0

        # Price momentum (deviation from neutral 0.5)
        price_momentum_24h = abs(market.yes_price - 0.5) * 2

        # Spread percentile (lower is better)
        spread_percentile = float(market.spread_bps)

        return {
            'volume_surge_ratio': round(volume_surge_ratio, 4),
            'liquidity_depth': round(liquidity_depth, 2),
            'price_momentum_24h': round(price_momentum_24h, 4),
            'spread_percentile': round(spread_percentile, 1),
        }

    def invalidate_cache(self, market_id: str) -> None:
        """Invalidate cached features for a specific market."""
        self._cache.invalidate(f'features:{market_id}')

    def clear_cache(self) -> None:
        """Clear all cached features."""
        self._cache.clear()
