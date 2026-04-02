"""Cross-platform arbitrage strategy — exploits price discrepancies across prediction markets.

Compares Polymarket prices with Manifold Markets, Metaculus, and Kalshi.
Fires when Polymarket deviates from cross-platform consensus by a significant margin.
"""

import logging

from polyclaw.config import settings
from polyclaw.data.cross_platform import CrossPlatformPrice, CrossPlatformPriceFetcher
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal

logger = logging.getLogger(__name__)

# Minimum number of platforms that must agree to form a consensus
_MIN_PLATFORMS_FOR_CONSENSUS = 2
# Default minimum discrepancy in basis points to trigger a signal
_DEFAULT_MIN_DISCREPANCY_BPS = 500


class CrossPlatformArbStrategy(BaseStrategy):
    """Strategy that detects price discrepancies across prediction market platforms."""

    strategy_id: str = 'cross_platform_arb'
    name: str = 'Cross-Platform Arbitrage'
    version: str = '1.0.0'

    def __init__(
        self,
        fetcher: CrossPlatformPriceFetcher | None = None,
        min_discrepancy_bps: int | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._min_discrepancy_bps = min_discrepancy_bps

    @property
    def enabled(self) -> bool:
        return bool(settings.llm_api_key) and settings.cross_platform_enabled

    def _get_fetcher(self) -> CrossPlatformPriceFetcher:
        if self._fetcher is None:
            self._fetcher = CrossPlatformPriceFetcher()
        return self._fetcher

    def _get_min_discrepancy_bps(self) -> int:
        if self._min_discrepancy_bps is not None:
            return self._min_discrepancy_bps
        return getattr(settings, 'cross_platform_min_discrepancy_bps', _DEFAULT_MIN_DISCREPANCY_BPS)

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Fetch cross-platform prices and compute consensus."""
        fetcher = self._get_fetcher()
        try:
            prices = fetcher.fetch_all_platforms(market.title)
        except Exception as exc:
            logger.debug('Cross-platform fetch failed for %s: %s', market.market_id, exc)
            return {'cross_platform_prices': [], 'consensus': None}

        if not prices:
            return {'cross_platform_prices': [], 'consensus': None}

        # Compute weighted consensus probability
        # Weight by similarity score
        total_weight = 0.0
        weighted_prob = 0.0
        platforms: set[str] = set()

        for price in prices:
            weight = price.similarity_score
            weighted_prob += price.probability_yes * weight
            total_weight += weight
            platforms.add(price.platform)

        if total_weight == 0:
            return {'cross_platform_prices': prices, 'consensus': None}

        consensus_prob = weighted_prob / total_weight

        return {
            'cross_platform_prices': prices,
            'consensus': {
                'probability_yes': consensus_prob,
                'platform_count': len(platforms),
                'platforms': sorted(platforms),
                'total_weight': total_weight,
            },
        }

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal when Polymarket deviates from cross-platform consensus."""
        prices: list[CrossPlatformPrice] = features.get('cross_platform_prices', [])
        consensus: dict | None = features.get('consensus')

        if not prices or consensus is None:
            return None

        platform_count = consensus.get('platform_count', 0)
        if platform_count < _MIN_PLATFORMS_FOR_CONSENSUS:
            return None

        consensus_prob = consensus.get('probability_yes', 0.5)
        discrepancy_bps = int((market.yes_price - consensus_prob) * 10000)

        min_discrepancy = self._get_min_discrepancy_bps()

        if abs(discrepancy_bps) < min_discrepancy:
            return None

        # Polymarket is overpriced → sell YES (buy NO)
        # Polymarket is underpriced → buy YES
        if discrepancy_bps > 0:
            # Polymarket YES price > consensus → Polymarket overpriced → buy NO
            side = Side.NO
            edge_bps = discrepancy_bps
        else:
            # Polymarket YES price < consensus → Polymarket underpriced → buy YES
            side = Side.YES
            edge_bps = -discrepancy_bps

        # Spread/liquidity filters
        if market.spread_bps > settings.max_spread_bps:
            return None
        if market.liquidity_usd < settings.min_liquidity_usd:
            return None

        # Confidence based on number of agreeing platforms and discrepancy size
        confidence = min(0.90, 0.5 + platform_count * 0.08 + edge_bps / 10000)

        platform_list = ', '.join(consensus.get('platforms', []))

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(confidence, 4),
            edge_bps=edge_bps,
            explanation=(
                f'Cross-platform arb: Polymarket YES={market.yes_price:.3f} vs '
                f'consensus={consensus_prob:.3f} from {platform_count} platforms '
                f'({platform_list}), discrepancy={discrepancy_bps}bps'
            ),
            model_probability=consensus_prob,
            market_implied_probability=market.yes_price,
            features_used={
                'consensus_prob': round(consensus_prob, 4),
                'discrepancy_bps': discrepancy_bps,
                'platform_count': platform_count,
                'platforms': consensus.get('platforms', []),
                'price_count': len(prices),
            },
        )
