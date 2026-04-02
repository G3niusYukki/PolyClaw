"""Tests for sentiment analysis module."""

from unittest.mock import MagicMock

import pytest

from polyclaw.data.news_fetcher import NewsArticle
from polyclaw.data.sentiment import SentimentAnalyzer, SentimentResult


def _make_articles(count=3):
    return [
        NewsArticle(title=f'Article {i}', snippet=f'Snippet {i}', source='test', url=f'http://a.com/{i}')
        for i in range(count)
    ]


class TestSentimentAnalyzer:
    def test_returns_neutral_for_empty_articles(self):
        mock_llm = MagicMock()
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', [], baseline_probability=0.6)
        assert result is not None
        assert result.direction == 'neutral'
        assert result.articles_analyzed == 0
        assert result.adjusted_probability == 0.6

    def test_returns_result_on_valid_response(self):
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = {
            'direction': 'bullish',
            'magnitude': 0.7,
            'adjusted_probability_yes': 0.75,
            'key_insights': ['Strong economic data', 'Positive outlook'],
            'reasoning': 'test',
        }
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', _make_articles(), baseline_probability=0.6)
        assert result is not None
        assert result.direction == 'bullish'
        assert result.magnitude == 0.7
        assert result.adjusted_probability == 0.75
        assert len(result.key_insights) == 2

    def test_returns_none_on_llm_failure(self):
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = None
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', _make_articles(), baseline_probability=0.5)
        assert result is None

    def test_clamps_invalid_direction(self):
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = {
            'direction': 'invalid_direction',
            'magnitude': 0.5,
            'adjusted_probability_yes': 0.6,
        }
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', _make_articles(), baseline_probability=0.5)
        assert result is not None
        assert result.direction == 'neutral'

    def test_clamps_magnitude(self):
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = {
            'direction': 'bearish',
            'magnitude': 2.0,
            'adjusted_probability_yes': 0.3,
        }
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', _make_articles(), baseline_probability=0.5)
        assert result is not None
        assert result.magnitude == 1.0

    def test_clamps_adjusted_probability(self):
        mock_llm = MagicMock()
        mock_llm.complete_json.return_value = {
            'direction': 'bullish',
            'magnitude': 0.5,
            'adjusted_probability_yes': 1.5,
        }
        analyzer = SentimentAnalyzer(mock_llm)
        result = analyzer.analyze_articles('Will X?', _make_articles(), baseline_probability=0.5)
        assert result is not None
        assert result.adjusted_probability == 0.99
