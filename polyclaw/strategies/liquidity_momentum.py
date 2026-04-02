from dataclasses import dataclass

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.strategies.utils import calculate_liquidity_depth
from polyclaw.timeutils import utcnow


@dataclass
class LiquidityMomentumConfig:
    max_position_pct: float = 10.0
    max_drawdown_pct: float = 10.0
    max_daily_trades: int = 5
    momentum_threshold: float = 0.3
    volume_surge_min: float = 0.05
    liquidity_depth_min_usd: float = 3000.0


class LiquidityMomentumStrategy(BaseStrategy):
    """Liquidity Momentum strategy — enters when volume spikes and price is breaking out.

    This strategy detects momentum conditions by combining volume surge analysis,
    liquidity depth checks, and price momentum signals. It adapts ranking logic
    from the MarketRanker for momentum detection.
    """

    strategy_id: str = "liquidity_momentum"
    name: str = "Liquidity Momentum"
    version: str = "1.0.0"

    def __init__(self, config: LiquidityMomentumConfig | None = None) -> None:
        self.config = config or LiquidityMomentumConfig()

    @property
    def enabled(self) -> bool:
        return True

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Calculate liquidity and momentum features for a market."""
        volume_surge_ratio = self._volume_surge_ratio(market)
        liquidity_depth = self._liquidity_depth(market)
        price_momentum_24h = self._price_momentum_24h(market)
        spread_percentile = self._spread_percentile(market)
        momentum_score = self._momentum_score(market, volume_surge_ratio)

        return {
            "volume_surge_ratio": volume_surge_ratio,
            "liquidity_depth": liquidity_depth,
            "price_momentum_24h": price_momentum_24h,
            "spread_percentile": spread_percentile,
            "momentum_score": momentum_score,
        }

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal for volume spike + breakout + sufficient depth."""
        volume_surge = features.get("volume_surge_ratio", 0.0)
        liquidity_depth = features.get("liquidity_depth", 0.0)
        momentum_score = features.get("momentum_score", 0.0)
        spread_pct = features.get("spread_percentile", 999)

        # Check volume surge threshold
        if volume_surge < self.config.volume_surge_min:
            return None

        # Check liquidity depth
        if liquidity_depth < self.config.liquidity_depth_min_usd:
            return None

        # Check momentum threshold
        if momentum_score < self.config.momentum_threshold:
            return None

        # Spread quality check
        if spread_pct > 400:
            return None

        # Calculate confidence from momentum composite
        confidence = min(0.95, 0.5 + momentum_score * 0.5)

        # Direction from price momentum
        yes_price = market.yes_price
        if yes_price > 0.55:
            side = Side.YES
            model_prob = min(0.97, max(0.03, yes_price + momentum_score * 0.1))
        elif yes_price < 0.45:
            side = Side.NO
            model_prob = min(0.97, max(0.03, (1 - yes_price) + momentum_score * 0.1))
        else:
            # Near-neutral price — require stronger momentum signal
            if momentum_score < 0.5:
                return None
            # Default to YES for slight positive momentum near-neutral
            side = Side.YES
            model_prob = min(0.97, max(0.03, 0.5 + momentum_score * 0.15))

        # Calculate edge
        if side == Side.YES:
            implied = market.yes_price
            edge = int((model_prob - implied) * 10000)
        else:
            implied = market.no_price
            edge = int(((1 - model_prob) - implied) * 10000)

        if edge < settings.min_edge_bps:
            return None

        explanation = (
            f"Liquidity Momentum: momentum_score={momentum_score:.3f}, "
            f"volume_surge={volume_surge:.3f}, liquidity_depth=${liquidity_depth:.0f}, "
            f"spread_pct={spread_pct:.0f}bps, confidence={confidence:.3f}, edge_bps={edge}."
        )

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(confidence, 4),
            edge_bps=edge,
            explanation=explanation,
            features_used={
                "volume_surge_ratio": round(volume_surge, 3),
                "liquidity_depth": round(liquidity_depth, 2),
                "price_momentum_24h": round(features.get("price_momentum_24h", 0.0), 3),
                "spread_percentile": round(spread_pct, 1),
                "momentum_score": round(momentum_score, 3),
            },
        )

    def validate(self) -> bool:
        return (
            self.enabled
            and self.config.max_position_pct > 0
            and self.config.max_drawdown_pct > 0
            and self.config.max_daily_trades > 0
            and self.config.momentum_threshold >= 0
            and self.config.volume_surge_min >= 0
            and self.config.liquidity_depth_min_usd >= 0
        )

    def _volume_surge_ratio(self, market: MarketSnapshot) -> float:
        """Volume surge as ratio of 24h volume to total liquidity."""
        if market.liquidity_usd <= 0:
            return 0.0
        return market.volume_24h_usd / market.liquidity_usd

    def _liquidity_depth(self, market: MarketSnapshot) -> float:
        """Liquidity depth score — higher is better, capped at meaningful levels."""
        return calculate_liquidity_depth(market.liquidity_usd)

    def _price_momentum_24h(self, market: MarketSnapshot) -> float:
        """Price momentum as deviation from neutral probability."""
        return abs(market.yes_price - 0.5) * 2

    def _spread_percentile(self, market: MarketSnapshot) -> float:
        """Return the spread in bps as-is (lower is better for execution quality)."""
        return float(market.spread_bps)

    def _momentum_score(self, market: MarketSnapshot, volume_surge: float) -> float:
        """Composite momentum score combining volume and price signals.

        Adapts scoring from MarketRanker for strategy use.
        """
        score = 0.0

        # Volume component
        if market.volume_24h_usd >= 5000:
            score += 0.3
        elif market.volume_24h_usd >= 1000:
            score += 0.15

        # Volume surge bonus
        score += min(volume_surge * 2, 0.3)

        # Price momentum component (deviation from 0.5)
        momentum = abs(market.yes_price - 0.5)
        if momentum >= 0.15:
            score += 0.25
        elif momentum >= 0.05:
            score += 0.1

        # Spread component
        if 0 < market.spread_bps <= 150:
            score += 0.15
        elif market.spread_bps <= 400:
            score += 0.05

        # Time quality (markets with decent runway but not too far out)
        if market.closes_at:
            remaining = market.closes_at - utcnow()
            days = remaining.total_seconds() / 86400.0
            if 1 <= days <= 45:
                score += 0.1
            elif 45 < days <= 120:
                score += 0.05
            elif days < 1:
                score -= 0.1

        return max(0.0, min(score, 1.0))
