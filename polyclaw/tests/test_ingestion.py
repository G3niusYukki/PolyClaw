"""Smoke tests for the ingestion package."""

from datetime import date
from unittest.mock import MagicMock

from polyclaw.db import Base
from polyclaw.ingestion import BackfillRunner, MarketFetcher, OrderBookFetcher, TradeFetcher
from polyclaw.ingestion.fetchers import RateLimiter
from polyclaw.timeutils import utcnow


def make_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


class TestRateLimiter:
    def test_rate_limiter_wait_is_idempotent(self):
        limiter = RateLimiter(calls_per_second=100)
        limiter.last_call = 0.0
        # Should not raise
        limiter.wait()
        limiter.wait()


class TestMarketFetcher:
    def test_is_binary_accepts_binary_market(self):
        fetcher = MarketFetcher()
        raw = {
            'id': 'abc123',
            'outcomes': '["Yes", "No"]',
        }
        assert fetcher._is_binary(raw) is True

    def test_is_binary_rejects_non_binary(self):
        fetcher = MarketFetcher()
        raw = {'outcomes': '["A", "B", "C"]'}
        assert fetcher._is_binary(raw) is False

    def test_is_binary_rejects_invalid_json(self):
        fetcher = MarketFetcher()
        raw = {'outcomes': 'not-json'}
        assert fetcher._is_binary(raw) is False

    def test_is_binary_rejects_empty_outcomes(self):
        fetcher = MarketFetcher()
        raw = {'outcomes': '[]'}
        assert fetcher._is_binary(raw) is False

    def test_parse_market(self):
        fetcher = MarketFetcher()
        raw = {
            'id': 'm1',
            'question': 'Test market',
            'description': 'desc',
            'outcomes': '["Yes", "No"]',
            'outcomePrices': '[0.42, 0.58]',
            'bestAsk': '0.43',
            'bestBid': '0.41',
            'liquidityNum': '1234',
            'volume24hr': '100',
            'category': 'news',
            'slug': 'test-slug',
            'endDate': '2026-04-01T12:00:00Z',
        }
        market = fetcher._parse_market(raw)
        assert market.market_id == 'm1'
        assert market.yes_price == 0.42
        assert market.no_price == 0.58
        assert market.spread_bps == 200
        assert market.liquidity_usd == 1234.0
        assert market.category == 'news'

    def test_parse_market_handles_missing_prices(self):
        fetcher = MarketFetcher()
        raw = {
            'id': 'm2',
            'question': 'Test',
            'outcomes': '["Yes", "No"]',
            'outcomePrices': '[]',
        }
        market = fetcher._parse_market(raw)
        assert market.yes_price == 0.0
        assert market.no_price == 0.0


class TestOrderBookFetcher:
    def test_parse_order_book(self):
        fetcher = OrderBookFetcher()
        raw = {
            'bids': [
                {'price': '0.40', 'size': '100'},
                {'price': '0.39', 'size': '200'},
            ],
            'asks': [
                {'price': '0.42', 'size': '150'},
            ],
        }
        ob = fetcher._parse_order_book('m1', raw)
        assert ob.market_id == 'm1'
        assert len(ob.bids) == 2
        assert len(ob.asks) == 1
        assert round(ob.mid_price, 4) == 0.41
        assert round(ob.spread, 4) == 0.02

    def test_parse_order_book_empty(self):
        fetcher = OrderBookFetcher()
        raw = {'bids': [], 'asks': []}
        ob = fetcher._parse_order_book('m2', raw)
        assert ob.market_id == 'm2'
        assert len(ob.bids) == 0
        assert len(ob.asks) == 0
        assert ob.mid_price == 0.0

    def test_parse_order_book_skips_zero_prices(self):
        fetcher = OrderBookFetcher()
        raw = {
            'bids': [
                {'price': '0.40', 'size': '100'},
                {'price': '0.00', 'size': '0'},  # invalid
            ],
            'asks': [],
        }
        ob = fetcher._parse_order_book('m3', raw)
        assert len(ob.bids) == 1
        assert ob.bids[0].price == 0.40


class TestTradeFetcher:
    def test_parse_trade(self):
        fetcher = TradeFetcher()
        item = {
            'id': 't1',
            'price': '0.55',
            'size': '50',
            'outcome': 'yes',
            'takerSide': 'buy',
            'timestamp': '1740000000.0',
        }
        trade = fetcher._parse_trade('m1', item)
        assert trade.market_id == 'm1'
        assert trade.trade_id == 't1'
        assert trade.price == 0.55
        assert trade.size == 50
        assert trade.side == 'yes'

    def test_parse_trade_handles_missing_fields(self):
        fetcher = TradeFetcher()
        item = {'price': '0.5'}
        trade = fetcher._parse_trade('m2', item)
        assert trade.market_id == 'm2'
        assert trade.price == 0.5
        assert trade.timestamp is not None


class TestBackfillRunner:
    def test_fetch_markets_snapshot_stores_to_session(self):
        session = make_session()
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_markets.return_value = []

        runner = BackfillRunner(session=session, market_fetcher=mock_fetcher)
        result = runner.fetch_markets_snapshot(limit=10)
        assert result == []
        mock_fetcher.fetch_markets.assert_called_once()

    def test_fetch_historical_calls_fetcher_for_date_range(self):
        session = make_session()
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_all_markets.return_value = []

        runner = BackfillRunner(session=session, market_fetcher=mock_fetcher)
        start = date(2026, 3, 20)
        end = date(2026, 3, 22)
        counts = runner.fetch_historical(start, end)

        assert counts['markets'] == 0
        assert counts['order_books'] == 0
        assert counts['trades'] == 0

    def test_market_to_model(self):
        from polyclaw.domain import MarketSnapshot
        session = make_session()
        runner = BackfillRunner(session=session)

        market = MarketSnapshot(
            market_id='m-test',
            title='Test',
            description='desc',
            yes_price=0.5,
            no_price=0.5,
            spread_bps=100,
            liquidity_usd=1000,
            volume_24h_usd=100,
            category='test',
            event_key='ev-test',
            closes_at=None,
            fetched_at=utcnow(),
        )
        model = runner._market_to_model(market)
        assert model.market_id == 'm-test'
        assert model.title == 'Test'
        assert model.outcome_yes_price == 0.5
