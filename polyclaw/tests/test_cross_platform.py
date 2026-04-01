"""Tests for cross-platform price fetching."""

from unittest.mock import MagicMock, patch

import pytest

from polyclaw.data.cross_platform import (
    CrossPlatformPrice,
    CrossPlatformPriceFetcher,
    _compute_similarity,
    _extract_search_terms,
)


class TestExtractSearchTerms:
    def test_removes_will_prefix(self):
        assert _extract_search_terms('Will Trump win 2024?') == 'Trump win 2024'

    def test_removes_question_mark(self):
        assert _extract_search_terms('Is Bitcoin over 100k?') == 'Bitcoin over 100k'

    def test_takes_first_clause(self):
        result = _extract_search_terms('Will X happen, and will Y happen?')
        assert result == 'X happen'

    def test_limits_length(self):
        long_title = 'Will ' + 'x' * 200 + ' happen?'
        result = _extract_search_terms(long_title)
        assert len(result) <= 100


class TestComputeSimilarity:
    def test_identical_titles(self):
        score = _compute_similarity('Will Trump win?', 'Will Trump win?')
        assert score > 0.8

    def test_similar_titles(self):
        score = _compute_similarity(
            'Will Bitcoin reach $100k by end of year?',
            'Will Bitcoin reach $100k by December?',
        )
        assert score >= 0.5

    def test_dissimilar_titles(self):
        score = _compute_similarity(
            'Will Trump win 2024?',
            'Will it rain tomorrow?',
        )
        assert score < 0.3

    def test_empty_title(self):
        assert _compute_similarity('', 'Something') == 0.0
        assert _compute_similarity('Something', '') == 0.0


class TestCrossPlatformPriceFetcher:
    def test_close(self):
        fetcher = CrossPlatformPriceFetcher()
        fetcher.close()
        assert fetcher._http_client is None

    def test_fetch_manifold_prices_success(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'question': 'Will Trump win 2024?', 'probability': 0.55, 'volume': 10000},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_manifold_prices('Will Trump win 2024?')
            assert len(results) == 1
            assert results[0].platform == 'manifold'
            assert results[0].probability_yes == 0.55
            assert results[0].similarity_score > 0.3

    def test_fetch_manifold_skips_low_similarity(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'question': 'Will it rain in London?', 'probability': 0.7, 'volume': 0},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_manifold_prices('Will Bitcoin reach $100k?')
            assert len(results) == 0

    def test_fetch_manifold_handles_error(self):
        fetcher = CrossPlatformPriceFetcher()
        with patch.object(fetcher.http_client, 'get', side_effect=Exception('Network error')):
            results = fetcher.fetch_manifold_prices('test')
            assert results == []

    def test_fetch_metaculus_prices_success(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'results': [
                {
                    'id': 123,
                    'title': 'Will Bitcoin reach $100k?',
                    'community_prediction': {'yes': 0.65},
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_metaculus_prices('Will Bitcoin reach $100k?')
            assert len(results) == 1
            assert results[0].platform == 'metaculus'
            assert results[0].probability_yes == 0.65

    def test_fetch_metaculus_handles_error(self):
        fetcher = CrossPlatformPriceFetcher()
        with patch.object(fetcher.http_client, 'get', side_effect=Exception('fail')):
            assert fetcher.fetch_metaculus_prices('test') == []

    def test_fetch_kalshi_prices_success(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'markets': [
                {'title': 'Will Trump win 2024?', 'yes_price': 55},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_kalshi_prices('Will Trump win 2024?')
            assert len(results) == 1
            assert results[0].platform == 'kalshi'
            assert results[0].probability_yes == 0.55

    def test_fetch_kalshi_handles_price_over_one(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'markets': [
                {'title': 'Will Trump win 2024?', 'yes_price': 75},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_kalshi_prices('Will Trump win 2024?')
            assert results[0].probability_yes == 0.75

    def test_fetch_kalshi_handles_error(self):
        fetcher = CrossPlatformPriceFetcher()
        with patch.object(fetcher.http_client, 'get', side_effect=Exception('fail')):
            assert fetcher.fetch_kalshi_prices('test') == []

    def test_fetch_all_platforms(self):
        fetcher = CrossPlatformPriceFetcher()
        manifold_resp = MagicMock()
        manifold_resp.json.return_value = [
            {'question': 'Will Trump win?', 'probability': 0.55, 'volume': 100},
        ]
        manifold_resp.raise_for_status = MagicMock()

        metaculus_resp = MagicMock()
        metaculus_resp.json.return_value = {
            'results': [
                {'id': 1, 'title': 'Will Trump win?', 'community_prediction': {'yes': 0.60}},
            ]
        }
        metaculus_resp.raise_for_status = MagicMock()

        kalshi_resp = MagicMock()
        kalshi_resp.json.return_value = {
            'markets': [
                {'title': 'Will Trump win?', 'yes_price': 58},
            ]
        }
        kalshi_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if 'manifold' in url:
                return manifold_resp
            elif 'metaculus' in url:
                return metaculus_resp
            elif 'kalshi' in url:
                return kalshi_resp
            raise ValueError(f'Unknown URL: {url}')

        with patch.object(fetcher.http_client, 'get', side_effect=mock_get):
            results = fetcher.fetch_all_platforms('Will Trump win?')
            assert len(results) == 3
            platforms = {r.platform for r in results}
            assert platforms == {'manifold', 'metaculus', 'kalshi'}

    def test_fetch_all_platforms_continues_on_failure(self):
        fetcher = CrossPlatformPriceFetcher()

        def mock_get(url, **kwargs):
            if 'manifold' in url:
                raise Exception('Manifold down')
            resp = MagicMock()
            resp.json.return_value = {
                'results': [{'id': 1, 'title': 'Will X happen?', 'community_prediction': {'yes': 0.6}}],
            }
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(fetcher.http_client, 'get', side_effect=mock_get):
            results = fetcher.fetch_all_platforms('Will X happen?')
            # Manifold fails but Metaculus should work (Kalshi may fail on similarity)
            assert any(r.platform == 'metaculus' for r in results)

    def test_manifold_skips_items_without_probability(self):
        fetcher = CrossPlatformPriceFetcher()
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'question': 'Will Trump win?', 'volume': 100},  # no probability
            {'question': 'Will Trump win?', 'probability': None, 'volume': 100},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.http_client, 'get', return_value=mock_response):
            results = fetcher.fetch_manifold_prices('Will Trump win?')
            assert len(results) == 0
