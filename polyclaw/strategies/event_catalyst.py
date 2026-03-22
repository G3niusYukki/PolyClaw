from dataclasses import dataclass

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.timeutils import utcnow


@dataclass
class EventCatalystConfig:
    min_days_to_resolution: float = 3.0
    max_days_to_resolution: float = 30.0
    min_confidence: float = 0.62


class EventCatalystStrategy(BaseStrategy):
    """Event Catalyst strategy — trades high-conviction events approaching resolution.

    This strategy identifies markets where a clear event catalyst is approaching
    (days to resolution within a defined window) and generates signals when
    conviction exceeds a threshold. It adapts the scoring logic from the original
    StrategyEngine.
    """

    strategy_id: str = 'event_catalyst'
    name: str = 'Event Catalyst'
    version: str = '1.0.0'

    def __init__(self, config: EventCatalystConfig | None = None) -> None:
        self.config = config or EventCatalystConfig(
            min_days_to_resolution=settings.min_days_to_resolution
            if hasattr(settings, 'min_days_to_resolution')
            else 3.0,
            max_days_to_resolution=settings.max_days_to_resolution
            if hasattr(settings, 'max_days_to_resolution')
            else 30.0,
            min_confidence=settings.min_confidence,
        )

    @property
    def enabled(self) -> bool:
        return True

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Calculate event-catalyst features for a market."""
        now = utcnow()

        # Days to resolution
        if market.closes_at:
            remaining = market.closes_at - now
            days_to_resolution = remaining.total_seconds() / 86400.0
        else:
            days_to_resolution = -1.0

        # Event category detection
        event_category = self._classify_event(market.title, market.category)

        # Volume surge ratio (volume vs historical baseline)
        volume_surge_ratio = self._compute_volume_surge(market)

        # Price momentum (heuristic based on yes_price deviation from 0.5)
        price_momentum = self._compute_momentum(market)

        # News sentiment (heuristic keyword-based)
        news_sentiment = self._compute_sentiment(market.title)

        return {
            'days_to_resolution': days_to_resolution,
            'event_category': event_category,
            'volume_surge_ratio': volume_surge_ratio,
            'price_momentum': price_momentum,
            'news_sentiment': news_sentiment,
        }

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal for high-conviction events near resolution."""
        days = features.get('days_to_resolution', -1.0)
        category = features.get('event_category', 'unknown')
        sentiment = features.get('news_sentiment', 0.0)

        # Filter by resolution window
        if days < 0:
            return None
        if days < self.config.min_days_to_resolution:
            return None
        if days > self.config.max_days_to_resolution:
            return None

        # Compute conviction from sentiment and event type
        conviction_score = self._compute_conviction(features)

        # Adjust conviction based on event category
        if category == 'information_event':
            conviction_score += 0.1
        elif category == 'novelty':
            conviction_score -= 0.15

        confidence = min(max(conviction_score, 0.0), 0.95)

        if confidence < self.config.min_confidence:
            return None

        # Direction based on sentiment
        if sentiment >= 0.05:
            side = Side.YES
            # Model YES probability shifts from 0.5 by sentiment magnitude
            model_prob_yes = min(0.97, max(0.03, 0.5 + abs(sentiment)))
        elif sentiment <= -0.05:
            side = Side.NO
            model_prob_yes = min(0.97, max(0.03, 0.5 - abs(sentiment)))
        else:
            return None

        # Calculate edge
        if side == Side.YES:
            implied = market.yes_price
            edge = int((model_prob_yes - implied) * 10000)
        else:
            implied = market.no_price
            model_no_prob = 1 - model_prob_yes
            edge = int((model_no_prob - implied) * 10000)

        if edge < settings.min_edge_bps:
            return None

        # Filter by spread
        if market.spread_bps > settings.max_spread_bps:
            return None

        # Filter by liquidity
        if market.liquidity_usd < settings.min_liquidity_usd:
            return None

        explanation = (
            f'Event Catalyst: category={category}, sentiment={sentiment:.2f}, '
            f'days_to_resolution={days:.1f}, confidence={confidence:.3f}, edge_bps={edge}, '
            f'market_yes={market.yes_price:.3f}, model_prob_yes={model_prob_yes:.3f}.'
        )

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(confidence, 4),
            edge_bps=edge,
            explanation=explanation,
            features_used={
                'days_to_resolution': round(days, 2),
                'event_category': category,
                'news_sentiment': round(sentiment, 3),
                'volume_surge_ratio': round(features.get('volume_surge_ratio', 0.0), 3),
                'price_momentum': round(features.get('price_momentum', 0.0), 3),
            },
        )

    def validate(self) -> bool:
        return (
            self.enabled
            and self.config.min_days_to_resolution >= 0
            and self.config.max_days_to_resolution >= self.config.min_days_to_resolution
            and 0 <= self.config.min_confidence <= 1.0
        )

    def _classify_event(self, title: str, category: str) -> str:
        title_lower = title.lower()
        if any(
            token in title_lower
            for token in ['convicted', 'ceasefire', 'election', 'trial', 'verdict', 'verdict', 'win', 'lose', 'pass', 'fail']
        ):
            return 'information_event'
        if any(
            token in title_lower
            for token in ['gta vi', 'jesus christ', 'album before', 'before gta', 'before album']
        ):
            return 'novelty'
        if category in ['politics', 'news', 'macro', 'economy', 'science']:
            return 'information_event'
        return 'unknown'

    def _compute_volume_surge(self, market: MarketSnapshot) -> float:
        """Compute volume surge as ratio of 24h volume to liquidity."""
        if market.liquidity_usd <= 0:
            return 0.0
        return market.volume_24h_usd / market.liquidity_usd

    def _compute_momentum(self, market: MarketSnapshot) -> float:
        """Compute price momentum as deviation from 0.5 (neutral probability)."""
        return abs(market.yes_price - 0.5) * 2

    def _compute_conviction(self, features: dict) -> float:
        """Compute overall conviction score from features."""
        sentiment = features.get('news_sentiment', 0.0)
        volume_surge = features.get('volume_surge_ratio', 0.0)
        price_momentum = features.get('price_momentum', 0.0)
        return 0.45 + abs(sentiment) * 0.3 + volume_surge * 0.1 + price_momentum * 0.15  # type: ignore[no-any-return]

    def _compute_sentiment(self, title: str) -> float:
        """Heuristic sentiment from title keywords."""
        title_lower = title.lower()
        positive_tokens = ['win', 'pass', 'approved', 'confirmed', 'elected', 'cut', 'deal', 'ceasefire']
        negative_tokens = ['lose', 'fail', 'rejected', 'convicted', 'decline', 'war', 'crash']
        neutral_tokens = ['will', 'before', 'after', 'during']

        score = 0.0
        for token in positive_tokens:
            if token in title_lower:
                score += 0.15
        for token in negative_tokens:
            if token in title_lower:
                score -= 0.15
        for token in neutral_tokens:
            if token in title_lower:
                score += 0.0

        # YES price itself carries signal
        return max(-1.0, min(1.0, score))
