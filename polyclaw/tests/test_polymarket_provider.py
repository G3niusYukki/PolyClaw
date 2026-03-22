from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider

SAMPLE = [{
    'id': '123',
    'question': 'Will example happen?',
    'description': 'demo',
    'outcomes': '["Yes", "No"]',
    'outcomePrices': '["0.42", "0.58"]',
    'bestAsk': '0.43',
    'bestBid': '0.41',
    'liquidityNum': '12345.6',
    'volume24hr': '234.5',
    'category': 'news',
    'slug': 'will-example-happen',
    'endDate': '2026-04-01T12:00:00Z'
}]


class DummyProvider(PolymarketGammaProvider):
    def list_markets(self, limit: int):
        return [self._to_snapshot(item) for item in SAMPLE if self._is_binary(item)]


def test_polymarket_provider_parses_binary_market():
    markets = DummyProvider().list_markets(1)
    assert len(markets) == 1
    market = markets[0]
    assert market.market_id == '123'
    assert market.yes_price == 0.42
    assert market.no_price == 0.58
    assert market.spread_bps == 200
    assert market.liquidity_usd == 12345.6
