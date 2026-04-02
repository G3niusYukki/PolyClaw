"""Cross-platform price fetching for prediction market arbitrage detection."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import httpx

from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class CrossPlatformPrice:
    """A price for a similar market on another platform."""
    platform: str  # 'manifold', 'metaculus', 'kalshi'
    title: str
    probability_yes: float  # 0.0 to 1.0
    volume_usd: float = 0.0
    url: str = ''
    similarity_score: float = 0.0  # 0.0 to 1.0, how well it matches
    fetched_at: datetime | None = None


class CrossPlatformPriceFetcher:
    """Fetches prices from alternative prediction market platforms."""

    def __init__(self) -> None:
        self._http_client: httpx.Client | None = None

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=15.0)
        return self._http_client

    def close(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def fetch_all_platforms(
        self,
        market_title: str,
        max_results_per_platform: int = 5,
    ) -> list[CrossPlatformPrice]:
        """Fetch matching markets from all platforms.

        Args:
            market_title: The Polymarket title to search for.
            max_results_per_platform: Max results per platform.

        Returns:
            List of CrossPlatformPrice from all platforms.
        """
        results: list[CrossPlatformPrice] = []
        fetchers = [
            self.fetch_manifold_prices,
            self.fetch_metaculus_prices,
            self.fetch_kalshi_prices,
        ]
        for fetcher in fetchers:
            try:
                platform_results = fetcher(market_title, max_results_per_platform)
                results.extend(platform_results)
            except Exception as exc:
                logger.debug('Cross-platform fetch failed (%s): %s', fetcher.__name__, exc)
        return results

    def fetch_manifold_prices(
        self,
        market_title: str,
        max_results: int = 5,
    ) -> list[CrossPlatformPrice]:
        """Fetch matching markets from Manifold Markets.

        Manifold Markets has a public API at https://manifold.markets/api/v0/.
        """
        search_terms = _extract_search_terms(market_title)
        results: list[CrossPlatformPrice] = []

        try:
            resp = self.http_client.get(
                'https://manifold.markets/api/v0/search-markets',
                params={'term': search_terms, 'limit': max_results},
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = item.get('question', '') or item.get('title', '')
                prob = item.get('probability', None)
                if prob is None:
                    continue
                similarity = _compute_similarity(market_title, title)
                if similarity < 0.3:
                    continue
                results.append(CrossPlatformPrice(
                    platform='manifold',
                    title=title,
                    probability_yes=float(prob),
                    volume_usd=float(item.get('volume', 0) or 0),
                    url=item.get('url', ''),
                    similarity_score=similarity,
                    fetched_at=utcnow(),
                ))
        except Exception as exc:
            logger.debug('Manifold fetch failed: %s', exc)

        return results

    def fetch_metaculus_prices(
        self,
        market_title: str,
        max_results: int = 5,
    ) -> list[CrossPlatformPrice]:
        """Fetch matching markets from Metaculus.

        Metaculus has a public API at https://www.metaculus.com/api2/.
        """
        search_terms = _extract_search_terms(market_title)
        results: list[CrossPlatformPrice] = []

        try:
            resp = self.http_client.get(
                'https://www.metaculus.com/api2/questions/',
                params={'search': search_terms, 'limit': max_results, 'order_by': '-activity'},
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get('results', []) if isinstance(data, dict) else data
            for item in items[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = item.get('title', '')
                # Metaculus has community_prediction as a nested dict
                cp = item.get('community_prediction', {})
                prob = None
                if isinstance(cp, dict):
                    prob = cp.get('yes', None) or cp.get('p_yes', None) or cp.get('mean', None)
                if prob is None:
                    # Try top-level fields
                    prob = item.get('probability_yes', None) or item.get('prediction', None)
                if prob is None:
                    continue
                similarity = _compute_similarity(market_title, title)
                if similarity < 0.3:
                    continue
                results.append(CrossPlatformPrice(
                    platform='metaculus',
                    title=title,
                    probability_yes=float(prob),
                    volume_usd=float(item.get('volume', 0) or 0),
                    url=f"https://www.metaculus.com/questions/{item.get('id', '')}/",
                    similarity_score=similarity,
                    fetched_at=utcnow(),
                ))
        except Exception as exc:
            logger.debug('Metaculus fetch failed: %s', exc)

        return results

    def fetch_kalshi_prices(
        self,
        market_title: str,
        max_results: int = 5,
    ) -> list[CrossPlatformPrice]:
        """Fetch matching markets from Kalshi.

        Kalshi has a public API at https://api.elections.kalshi.com/cdn-api/.
        """
        search_terms = _extract_search_terms(market_title)
        results: list[CrossPlatformPrice] = []

        try:
            resp = self.http_client.get(
                'https://api.elections.kalshi.com/cdn-api/markets',
                params={'search_term': search_terms, 'limit': max_results},
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get('markets', []) if isinstance(data, dict) else data
            for item in items[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = item.get('title', '') or item.get('question', '')
                # Kalshi prices are in cents (0-100)
                last_price = item.get('last_price', None) or item.get('yes_price', None)
                if last_price is None:
                    continue
                prob = float(last_price)
                if prob > 1.0:
                    prob = prob / 100.0
                prob = max(0.01, min(0.99, prob))
                similarity = _compute_similarity(market_title, title)
                if similarity < 0.3:
                    continue
                results.append(CrossPlatformPrice(
                    platform='kalshi',
                    title=title,
                    probability_yes=prob,
                    volume_usd=float(item.get('volume', 0) or item.get('volume_num', 0) or 0),
                    url='',
                    similarity_score=similarity,
                    fetched_at=utcnow(),
                ))
        except Exception as exc:
            logger.debug('Kalshi fetch failed: %s', exc)

        return results


def _extract_search_terms(title: str) -> str:
    """Extract search terms from a Polymarket title."""
    # Remove common prefixes
    terms = re.sub(r'^(Will|Is|Are|Does|Do|Has|Have|Can|Could|Should|Shall)\s+', '', title, flags=re.IGNORECASE)
    # Remove question marks
    terms = terms.replace('?', '')
    # Take first meaningful clause
    terms = terms.split(',')[0].strip()
    # Limit length
    if len(terms) > 100:
        terms = terms[:100]
    return terms


def _compute_similarity(title_a: str, title_b: str) -> float:
    """Compute simple word-overlap similarity between two titles.

    Returns a value between 0.0 and 1.0.
    """
    stop_words = {'a', 'an', 'the', 'will', 'is', 'are', 'does', 'do', 'has',
                  'have', 'can', 'could', 'should', 'shall', 'in', 'on', 'at',
                  'to', 'for', 'of', 'and', 'or', 'be', 'by', 'this', 'that',
                  'it', 'if', 'not', 'no', 'yes'}

    def tokenize(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r'\w+', text) if w.lower() not in stop_words and len(w) > 2}

    set_a = tokenize(title_a)
    set_b = tokenize(title_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)
