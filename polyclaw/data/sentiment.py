"""LLM-based sentiment analysis for news articles."""

import json
import logging
from dataclasses import dataclass

from polyclaw.data.news_fetcher import NewsArticle
from polyclaw.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """Result of sentiment analysis for a market's news."""
    direction: str  # 'bullish', 'bearish', 'neutral'
    magnitude: float  # 0.0 to 1.0
    adjusted_probability: float  # LLM-adjusted probability of YES
    key_insights: list[str]
    articles_analyzed: int


class SentimentAnalyzer:
    """Uses LLM to analyze news sentiment for prediction markets."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    def analyze_articles(
        self,
        market_title: str,
        articles: list[NewsArticle],
        baseline_probability: float = 0.5,
    ) -> SentimentResult | None:
        """Analyze news articles and return sentiment assessment.

        Args:
            market_title: The prediction market question.
            articles: List of news articles to analyze.
            baseline_probability: The LLM baseline probability estimate.

        Returns:
            SentimentResult or None if analysis fails.
        """
        if not articles:
            return SentimentResult(
                direction='neutral',
                magnitude=0.0,
                adjusted_probability=baseline_probability,
                key_insights=[],
                articles_analyzed=0,
            )

        system_prompt, user_prompt = self._build_prompts(market_title, articles, baseline_probability)
        result = self._llm.complete_json(system_prompt, user_prompt)
        if result is None:
            logger.warning('Sentiment analysis failed for market: %s', market_title[:60])
            return None

        return self._parse_result(result, baseline_probability, len(articles))

    def _build_prompts(
        self,
        market_title: str,
        articles: list[NewsArticle],
        baseline_probability: float,
    ) -> tuple[str, str]:
        articles_text = '\n'.join(
            f'- [{a.source}] {a.title}'
            for a in articles[:10]
        )

        system_prompt = """\
You are a news sentiment analyst for prediction markets.
Analyze the provided news articles and determine their impact on the given market question.

Respond with JSON:
{
    "direction": "bullish" | "bearish" | "neutral",
    "magnitude": 0.0 to 1.0,
    "adjusted_probability_yes": 0.01 to 0.99,
    "key_insights": ["insight1", "insight2"],
    "reasoning": "brief explanation"
}

Rules:
- "bullish" means news supports YES outcome, "bearish" supports NO
- magnitude reflects strength of evidence (0 = no impact, 1 = very strong)
- adjusted_probability_yes should shift from baseline based on news impact
- Be conservative: only strong news should shift probability significantly"""

        user_prompt = f"""\
Market: {market_title}
Baseline probability: {baseline_probability:.2f}

Recent news:
{articles_text}

Analyze the sentiment of these articles relative to this market question."""

        return system_prompt, user_prompt

    def _parse_result(self, data: dict, baseline: float, article_count: int) -> SentimentResult:
        direction = data.get('direction', 'neutral')
        if direction not in ('bullish', 'bearish', 'neutral'):
            direction = 'neutral'

        magnitude = float(data.get('magnitude', 0.0))
        magnitude = max(0.0, min(1.0, magnitude))

        adjusted = data.get('adjusted_probability_yes', baseline)
        try:
            adjusted = max(0.01, min(0.99, float(adjusted)))
        except (TypeError, ValueError):
            adjusted = baseline

        insights = data.get('key_insights', [])
        if not isinstance(insights, list):
            insights = [str(insights)]
        insights = [str(i) for i in insights[:5]]

        return SentimentResult(
            direction=direction,
            magnitude=magnitude,
            adjusted_probability=adjusted,
            key_insights=insights,
            articles_analyzed=article_count,
        )
