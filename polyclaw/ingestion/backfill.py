"""Historical backfill runner for PolyClaw data ingestion.

Orchestrates fetching market data, order books, and trades over a
date range and persisting them to the database.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Generator

from sqlalchemy.orm import Session

from polyclaw.domain import MarketSnapshot, OrderBookSnapshot, Trade
from polyclaw.ingestion.fetchers import MarketFetcher, OrderBookFetcher, TradeFetcher
from polyclaw.repositories import upsert_market

logger = logging.getLogger(__name__)


class BackfillRunner:
    """Orchestrates historical data backfill from Polymarket.

    Args:
        session: SQLAlchemy session for database writes.
        market_fetcher: MarketFetcher instance (default: creates one).
        order_book_fetcher: OrderBookFetcher instance (default: creates one).
        trade_fetcher: TradeFetcher instance (default: creates one).
    """

    def __init__(
        self,
        session: Session,
        market_fetcher: MarketFetcher | None = None,
        order_book_fetcher: OrderBookFetcher | None = None,
        trade_fetcher: TradeFetcher | None = None,
    ):
        self.session = session
        self.market_fetcher = market_fetcher or MarketFetcher()
        self.order_book_fetcher = order_book_fetcher or OrderBookFetcher()
        self.trade_fetcher = trade_fetcher or TradeFetcher()

    def fetch_historical(
        self,
        start_date: date | datetime,
        end_date: date | datetime,
        include_order_books: bool = False,
        include_trades: bool = False,
        market_limit: int = 100,
    ) -> dict[str, int]:
        """Fetch historical data for all markets in the date range.

        Iterates over each day in the range and fetches markets that
        were active, optionally including order books and trades.

        Args:
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).
            include_order_books: Also fetch order books for each market.
            include_trades: Also fetch trades for each market.
            market_limit: Maximum markets to fetch per page.

        Returns:
            Dict with counts of 'markets', 'order_books', and 'trades' fetched.
        """
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()

        counts = {'markets': 0, 'order_books': 0, 'trades': 0}
        current = start_date

        while current <= end_date:
            logger.info("Fetching markets for date: %s", current)
            markets = self._fetch_markets_for_day(market_limit=market_limit)
            counts['markets'] += len(markets)

            for market in markets:
                self.session.merge(self._market_to_model(market))
                self.session.commit()

                if include_order_books:
                    try:
                        ob = self.order_book_fetcher.fetch_order_book(market.market_id)
                        self._save_order_book(ob)
                        counts['order_books'] += 1
                    except Exception as e:
                        logger.warning("Failed to fetch order book for %s: %s", market.market_id, e)

                if include_trades:
                    try:
                        trades = self.trade_fetcher.fetch_trades(market.market_id)
                        self._save_trades(trades)
                        counts['trades'] += len(trades)
                    except Exception as e:
                        logger.warning("Failed to fetch trades for %s: %s", market.market_id, e)

            current += timedelta(days=1)

        logger.info(
            "Backfill complete. markets=%d, order_books=%d, trades=%d",
            counts['markets'], counts['order_books'], counts['trades'],
        )
        return counts

    def fetch_markets_snapshot(
        self,
        limit: int = 100,
        closed: bool = False,
    ) -> list[MarketSnapshot]:
        """Fetch a snapshot of current markets (no date range iteration).

        Args:
            limit: Maximum number of markets to fetch.
            closed: Include closed markets.

        Returns:
            List of MarketSnapshot objects.
        """
        markets = self.market_fetcher.fetch_markets(limit=limit, closed=closed)
        for market in markets:
            self.session.merge(self._market_to_model(market))
        self.session.commit()
        return markets

    def _fetch_markets_for_day(self, market_limit: int) -> list[MarketSnapshot]:
        """Fetch all available markets (iterates pages)."""
        return self.market_fetcher.fetch_all_markets(limit=market_limit)

    def _market_to_model(self, market: MarketSnapshot):
        """Convert a MarketSnapshot to a database model."""
        from polyclaw.models import Market as MarketModel
        return MarketModel(
            market_id=market.market_id,
            title=market.title,
            description=market.description,
            outcome_yes_price=market.yes_price,
            outcome_no_price=market.no_price,
            spread_bps=market.spread_bps,
            liquidity_usd=market.liquidity_usd,
            volume_24h_usd=market.volume_24h_usd,
            category=market.category,
            event_key=market.event_key,
            closes_at=market.closes_at,
            fetched_at=market.fetched_at,
            is_active=True,
        )

    def _save_order_book(self, order_book: OrderBookSnapshot) -> None:
        """Persist an order book snapshot.

        Currently logs the order book; can be extended to write to a
        dedicated table or S3 depending on storage strategy.
        """
        logger.debug(
            "OrderBook market=%s bids=%d asks=%d mid_price=%.4f spread=%.4f",
            order_book.market_id,
            len(order_book.bids),
            len(order_book.asks),
            order_book.mid_price,
            order_book.spread,
        )

    def _save_trades(self, trades: list[Trade]) -> None:
        """Persist a list of trades.

        Currently logs the trades; can be extended to write to a
        dedicated table or S3 depending on storage strategy.
        """
        for trade in trades:
            logger.debug(
                "Trade market=%s id=%s side=%s price=%.4f size=%.4f ts=%s",
                trade.market_id,
                trade.trade_id,
                trade.side,
                trade.price,
                trade.size,
                trade.timestamp.isoformat(),
            )
