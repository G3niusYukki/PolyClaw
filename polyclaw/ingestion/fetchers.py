"""Data fetchers for Polymarket historical data ingestion.

Provides typed fetchers for markets, order books, and trades with
pagination support and rate limiting.
"""

import json
import time
from datetime import datetime
from urllib.request import Request, urlopen

from polyclaw.config import settings
from polyclaw.domain import (
    MarketSnapshot,
    OrderBookLevel,
    OrderBookSnapshot,
    Trade,
)
from polyclaw.timeutils import utcnow

POLYMARKET_GAMMA_BASE = settings.polymarket_gamma_url.rstrip('/')


class RateLimiter:
    """Simple token-bucket rate limiter."""

    def __init__(self, calls_per_second: float = 5.0):
        self.interval = 1.0 / calls_per_second
        self.last_call = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self.last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_call = time.time()


_limiter = RateLimiter()


def _get(url: str, timeout: int | None = None) -> dict | list:
    """Make a GET request and return parsed JSON."""
    timeout = timeout or settings.request_timeout_seconds
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    _limiter.wait()
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


class MarketFetcher:
    """Fetches market data from Polymarket Gamma API."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or POLYMARKET_GAMMA_BASE) + '/markets'

    def fetch_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        closed: bool = False,
        active: bool = True,
    ) -> list[MarketSnapshot]:
        """Fetch a page of markets from the Gamma API.

        Args:
            limit: Maximum number of markets per page (max 100).
            offset: Pagination offset.
            closed: Include closed markets.
            active: Include active markets.

        Returns:
            List of MarketSnapshot dataclasses for binary markets only.
        """
        params = {
            'limit': min(limit, 100),
            'offset': offset,
            'closed': str(closed).lower(),
            'active': str(active).lower(),
        }
        from urllib.parse import urlencode
        url = f'{self.base_url}?{urlencode(params)}'
        raw = _get(url)
        return [self._parse_market(item) for item in raw if self._is_binary(item)]

    def fetch_all_markets(
        self,
        limit: int = 100,
        max_pages: int = 50,
    ) -> list[MarketSnapshot]:
        """Fetch all markets by iterating pages until exhausted.

        Args:
            limit: Page size.
            max_pages: Maximum number of pages to fetch.

        Returns:
            Combined list of all MarketSnapshot objects.
        """
        all_markets: list[MarketSnapshot] = []
        for page in range(max_pages):
            offset = page * limit
            markets = self.fetch_markets(limit=limit, offset=offset)
            if not markets:
                break
            all_markets.extend(markets)
        return all_markets

    def _is_binary(self, item: dict) -> bool:
        try:
            outcomes = json.loads(item.get('outcomes') or '[]')
        except json.JSONDecodeError:
            return False
        return len(outcomes) == 2 and {o.lower() for o in outcomes} == {'yes', 'no'}

    def _parse_market(self, item: dict) -> MarketSnapshot:
        outcome_prices = json.loads(item.get('outcomePrices') or '[]')
        yes_price = float(outcome_prices[0]) if outcome_prices else 0.0
        no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.0
        closes_at: datetime | None = None
        raw_end = item.get('endDate') or item.get('endDateIso')
        if raw_end:
            try:
                closes_at = datetime.fromisoformat(raw_end.replace('Z', '+00:00')).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass
        best_ask = float(item.get('bestAsk') or 0)
        best_bid = float(item.get('bestBid') or 0)
        spread_bps = int(max(best_ask - best_bid, 0) * 10000) if best_ask and best_bid else 0
        return MarketSnapshot(
            market_id=str(item.get('id')),
            title=item.get('question') or item.get('title') or 'Untitled market',
            description=item.get('description') or '',
            yes_price=yes_price,
            no_price=no_price,
            spread_bps=spread_bps,
            liquidity_usd=float(item.get('liquidityNum') or item.get('liquidity') or 0),
            volume_24h_usd=float(
                item.get('volume24hr') or item.get('volume24h') or item.get('volume24Hr') or 0
            ),
            category=item.get('category') or 'general',
            event_key=item.get('slug') or str(item.get('id')),
            closes_at=closes_at,
            fetched_at=utcnow(),
        )


class OrderBookFetcher:
    """Fetches order book data for a specific market."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or POLYMARKET_GAMMA_BASE)

    def fetch_order_book(self, market_id: str) -> OrderBookSnapshot:
        """Fetch the current order book for a market.

        Args:
            market_id: The Polymarket market ID.

        Returns:
            OrderBookSnapshot with bids and asks.
        """
        url = f'{self.base_url}/markets/{market_id}/orderbook'
        raw = _get(url)
        return self._parse_order_book(market_id, raw)

    def _parse_order_book(self, market_id: str, raw: dict) -> OrderBookSnapshot:
        bids_raw = raw.get('bids') or []
        asks_raw = raw.get('asks') or []

        bids: list[OrderBookLevel] = []
        for entry in bids_raw:
            price = float(entry.get('price', 0))
            size = float(entry.get('size', 0))
            if price > 0 and size > 0:
                bids.append(OrderBookLevel(price=price, size=size, side='bid'))

        asks: list[OrderBookLevel] = []
        for entry in asks_raw:
            price = float(entry.get('price', 0))
            size = float(entry.get('size', 0))
            if price > 0 and size > 0:
                asks.append(OrderBookLevel(price=price, size=size, side='ask'))

        best_bid = bids[0].price if bids else 0.0
        best_ask = asks[0].price if asks else 0.0
        spread = max(best_ask - best_bid, 0.0)
        mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0

        return OrderBookSnapshot(
            market_id=market_id,
            bids=bids,
            asks=asks,
            spread=spread,
            mid_price=mid_price,
            fetched_at=utcnow(),
        )


class TradeFetcher:
    """Fetches recent trades for a specific market."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or POLYMARKET_GAMMA_BASE)

    def fetch_trades(
        self,
        market_id: str,
        limit: int = 100,
    ) -> list[Trade]:
        """Fetch recent trades for a market.

        Args:
            market_id: The Polymarket market ID.
            limit: Maximum number of trades to fetch.

        Returns:
            List of Trade dataclasses sorted by timestamp descending.
        """
        url = f'{self.base_url}/markets/{market_id}/trades?limit={min(limit, 500)}'
        raw = _get(url)
        if not isinstance(raw, list):
            return []
        return [self._parse_trade(market_id, item) for item in raw]

    def _parse_trade(self, market_id: str, item: dict) -> Trade:
        timestamp: datetime | None = None
        raw_ts = item.get('timestamp') or item.get('time') or item.get('date')
        if raw_ts:
            try:
                ts_float = float(raw_ts)
                timestamp = datetime.fromtimestamp(ts_float)
            except (ValueError, TypeError):
                timestamp = utcnow()
        else:
            timestamp = utcnow()

        price = float(item.get('price') or item.get('priceCumulative') or 0)
        size = float(item.get('size') or item.get('amount') or 0)

        return Trade(
            market_id=market_id,
            trade_id=str(item.get('id') or item.get('tradeId') or ''),
            side=item.get('outcome') or item.get('side') or 'yes',
            price=price,
            size=size,
            timestamp=timestamp,
            taker_side=item.get('takerSide') or item.get('taker_side') or 'buy',
        )
