"""News Catalyst strategy — combines LLM baseline probability with news sentiment.

Signal logic:
- 60% weight on LLM baseline probability estimate
- 40% weight on news sentiment-adjusted probability
- Only fires when both signals agree on direction
"""

import logging

from polyclaw.config import settings
from polyclaw.data.news_fetcher import NewsFetcher
from polyclaw.data.sentiment import SentimentAnalyzer
from polyclaw.domain import MarketSnapshot
from polyclaw.llm.client import LLMClient
from polyclaw.llm.parser import LLMProbabilityEstimate, parse_probability_response
from polyclaw.llm.prompts import build_probability_prompt
from polyclaw.strategies.base import BaseStrategy, Side, Signal

logger = logging.getLogger(__name__)

_BASELINE_WEIGHT = 0.6
_SENTIMENT_WEIGHT = 0.4


class NewsCatalystStrategy(BaseStrategy):
    """Strategy combining LLM probability with news sentiment analysis."""

    strategy_id: str = 'news_catalyst'
    name: str = 'News Catalyst'
    version: str = '1.0.0'

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        news_fetcher: NewsFetcher | None = None,
        max_articles: int = 5,
    ) -> None:
        self._llm = llm_client
        self._news_fetcher = news_fetcher
        self._max_articles = max_articles

    @property
    def enabled(self) -> bool:
        return bool(settings.llm_api_key) and settings.news_fetcher_enabled

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_news_fetcher(self) -> NewsFetcher:
        if self._news_fetcher is None:
            self._news_fetcher = NewsFetcher()
        return self._news_fetcher

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Compute LLM baseline + news sentiment features."""
        llm = self._get_llm()

        # Step 1: Get LLM baseline probability
        system_prompt, user_prompt = build_probability_prompt(market)
        raw = llm.complete(system_prompt, user_prompt)
        estimate = parse_probability_response(raw, market.market_id, settings.llm_model) if raw else None

        if estimate is None:
            logger.info('NewsCatalyst: LLM baseline failed for %s', market.market_id)
            return {'llm_estimate': None, 'sentiment': None}

        # Step 2: Fetch news articles
        fetcher = self._get_news_fetcher()
        articles = fetcher.fetch_news(market.title, max_articles=self._max_articles)
        logger.info('NewsCatalyst: fetched %d articles for %s', len(articles), market.market_id)

        # Step 3: Analyze sentiment
        analyzer = SentimentAnalyzer(llm)
        sentiment = analyzer.analyze_articles(
            market_title=market.title,
            articles=articles,
            baseline_probability=estimate.estimated_probability_yes,
        )

        return {
            'llm_estimate': estimate,
            'sentiment': sentiment,
            'articles_count': len(articles),
        }

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal when LLM and news sentiment align."""
        estimate: LLMProbabilityEstimate | None = features.get('llm_estimate')
        sentiment = features.get('sentiment')

        if estimate is None:
            return None

        # Calculate blended probability
        if sentiment is not None and sentiment.articles_analyzed > 0:
            # Both must agree on direction
            llm_direction = 'bullish' if estimate.estimated_probability_yes > market.yes_price else 'bearish'
            if llm_direction != 'neutral' and sentiment.direction != llm_direction:
                # Direction mismatch — no signal
                logger.info(
                    'NewsCatalyst: direction mismatch for %s (llm=%s, sentiment=%s)',
                    market.market_id, llm_direction, sentiment.direction,
                )
                return None

            blended_prob = (
                _BASELINE_WEIGHT * estimate.estimated_probability_yes
                + _SENTIMENT_WEIGHT * sentiment.adjusted_probability
            )
            # Boost confidence when both agree
            confidence = min(0.95, estimate.confidence + sentiment.magnitude * 0.1)
        else:
            # No news — fall back to pure LLM estimate
            blended_prob = estimate.estimated_probability_yes
            confidence = estimate.confidence

        # Minimum confidence
        if confidence < settings.min_confidence:
            return None

        # Calculate edge
        market_prob = market.yes_price
        edge_bps_yes = int((blended_prob - market_prob) * 10000)

        if edge_bps_yes > settings.min_edge_bps:
            side = Side.YES
            edge_bps = edge_bps_yes
        elif edge_bps_yes < -settings.min_edge_bps:
            side = Side.NO
            edge_bps = -edge_bps_yes
        else:
            return None

        # Spread/liquidity filters
        if market.spread_bps > settings.max_spread_bps:
            return None
        if market.liquidity_usd < settings.min_liquidity_usd:
            return None

        sentiment_info = ''
        if sentiment:
            sentiment_info = f', sentiment={sentiment.direction}({sentiment.magnitude:.2f})'
            if sentiment.key_insights:
                sentiment_info += f', insights={sentiment.key_insights[:2]}'

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(confidence, 4),
            edge_bps=edge_bps,
            explanation=(
                f'NewsCatalyst: blended_yes={blended_prob:.3f}, market_yes={market_prob:.3f}, '
                f'edge={edge_bps}bps, llm_conf={estimate.confidence:.3f}{sentiment_info}'
            ),
            model_probability=blended_prob,
            market_implied_probability=market_prob,
            features_used={
                'llm_probability_yes': round(estimate.estimated_probability_yes, 4),
                'blended_probability_yes': round(blended_prob, 4),
                'articles_count': features.get('articles_count', 0),
                'sentiment_direction': sentiment.direction if sentiment else 'none',
                'sentiment_magnitude': round(sentiment.magnitude, 3) if sentiment else 0.0,
            },
        )
