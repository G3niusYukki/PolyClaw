"""News article fetcher using Google News RSS."""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_RSS = 'https://news.google.com/rss/search'


@dataclass
class NewsArticle:
    """A single news article."""
    title: str
    snippet: str
    source: str
    url: str
    published_at: datetime = field(default_factory=datetime.utcnow)


class NewsFetcher:
    """Fetches news articles relevant to a prediction market."""

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def fetch_news(self, market_title: str, max_articles: int = 5) -> list[NewsArticle]:
        """Search for news articles related to a market.

        Args:
            market_title: The market title to search for related news.
            max_articles: Maximum number of articles to return.

        Returns:
            List of NewsArticle instances.
        """
        query = self._extract_search_terms(market_title)
        if not query:
            return []

        url = f'{_GOOGLE_NEWS_RSS}?{urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})}'
        try:
            resp = httpx.get(url, timeout=self._timeout, follow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning('News fetch failed for query=%r: %s', query, exc)
            return []

        articles = self._parse_rss(resp.text)
        return articles[:max_articles]

    def _extract_search_terms(self, title: str) -> str:
        """Extract meaningful search terms from a market title.

        Strips common prediction market boilerplate and keeps the core subject.
        """
        # Remove question marks and common market prefixes
        cleaned = title.replace('?', '')
        # Remove "Will " prefix if present
        cleaned = re.sub(r'^Will\s+', '', cleaned, flags=re.IGNORECASE)
        # Keep the first meaningful clause (before comma/semicolon)
        cleaned = re.split(r'[,;]', cleaned)[0].strip()
        # Limit length
        if len(cleaned) > 100:
            cleaned = cleaned[:100]
        return cleaned

    def _parse_rss(self, xml_text: str) -> list[NewsArticle]:
        """Parse Google News RSS XML into NewsArticle list."""
        articles: list[NewsArticle] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning('Failed to parse news RSS XML')
            return articles

        for item in root.iter('item'):
            title_el = item.find('title')
            link_el = item.find('link')
            source_el = item.find('source')
            pub_date_el = item.find('pubDate')

            if title_el is None or title_el.text is None:
                continue

            title = title_el.text
            # Google News titles often have " - Source Name" appended
            if ' - ' in title:
                title = title.rsplit(' - ', 1)[0]

            source = source_el.text if source_el is not None and source_el.text else 'unknown'
            url = link_el.text if link_el is not None and link_el.text else ''
            published = datetime.utcnow()
            if pub_date_el is not None and pub_date_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    published = parsedate_to_datetime(pub_date_el.text).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            articles.append(NewsArticle(
                title=title,
                snippet=title,  # Google News RSS doesn't include snippets
                source=source,
                url=url,
                published_at=published,
            ))
        return articles
