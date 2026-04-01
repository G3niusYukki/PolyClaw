"""Tests for news fetcher module."""

from unittest.mock import patch, MagicMock

import pytest

from polyclaw.data.news_fetcher import NewsFetcher, NewsArticle


class TestExtractSearchTerms:
    def test_simple_question(self):
        fetcher = NewsFetcher()
        result = fetcher._extract_search_terms('Will Bitcoin reach $100k?')
        assert 'Bitcoin' in result
        assert 'reach' in result

    def test_strips_will_prefix(self):
        fetcher = NewsFetcher()
        result = fetcher._extract_search_terms('Will the Fed cut rates?')
        assert not result.startswith('Will')

    def test_trims_at_comma(self):
        fetcher = NewsFetcher()
        result = fetcher._extract_search_terms('Will X happen, and if so, when?')
        assert ',' not in result

    def test_limits_length(self):
        fetcher = NewsFetcher()
        long_title = 'Will ' + 'a' * 200 + ' happen?'
        result = fetcher._extract_search_terms(long_title)
        assert len(result) <= 100


class TestParseRSS:
    def test_parse_valid_rss(self):
        fetcher = NewsFetcher()
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
            <title>Test Article - Source Name</title>
            <link>https://example.com/article</link>
            <source>Test Source</source>
            <pubDate>Mon, 01 Apr 2026 12:00:00 GMT</pubDate>
        </item></channel></rss>"""
        articles = fetcher._parse_rss(xml)
        assert len(articles) == 1
        assert articles[0].title == 'Test Article'
        assert articles[0].source == 'Test Source'

    def test_parse_empty_rss(self):
        fetcher = NewsFetcher()
        xml = '<?xml version="1.0"?><rss><channel></channel></rss>'
        articles = fetcher._parse_rss(xml)
        assert articles == []

    def test_parse_invalid_xml(self):
        fetcher = NewsFetcher()
        articles = fetcher._parse_rss('not xml')
        assert articles == []

    def test_parse_multiple_items(self):
        fetcher = NewsFetcher()
        xml = """<?xml version="1.0"?>
        <rss><channel>
            <item><title>Article 1</title><link>http://a.com</link></item>
            <item><title>Article 2</title><link>http://b.com</link></item>
        </channel></rss>"""
        articles = fetcher._parse_rss(xml)
        assert len(articles) == 2


class TestFetchNews:
    def test_returns_empty_on_network_error(self):
        fetcher = NewsFetcher()
        with patch('polyclaw.data.news_fetcher.httpx.get', side_effect=Exception('network error')):
            result = fetcher.fetch_news('Will X happen?')
            assert result == []

    def test_respects_max_articles(self):
        fetcher = NewsFetcher()
        xml_items = ''.join(
            f'<item><title>Article {i}</title><link>http://a.com/{i}</link></item>'
            for i in range(10)
        )
        xml = f'<?xml version="1.0"?><rss><channel>{xml_items}</channel></rss>'
        mock_resp = MagicMock()
        mock_resp.text = xml
        mock_resp.raise_for_status = MagicMock()

        with patch('polyclaw.data.news_fetcher.httpx.get', return_value=mock_resp):
            result = fetcher.fetch_news('Will X happen?', max_articles=3)
            assert len(result) == 3
