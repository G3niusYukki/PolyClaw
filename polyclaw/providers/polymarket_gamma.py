import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.timeutils import utcnow


class PolymarketGammaProvider:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.polymarket_gamma_url

    def list_markets(self, limit: int) -> list[MarketSnapshot]:
        params = urlencode({'limit': limit, 'active': 'true', 'closed': 'false'})
        url = f'{self.base_url}?{params}'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urlopen(req, timeout=settings.request_timeout_seconds) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        return [self._to_snapshot(item) for item in payload if self._is_binary(item)]

    def _is_binary(self, item: dict) -> bool:
        try:
            outcomes = json.loads(item.get('outcomes') or '[]')
        except json.JSONDecodeError:
            return False
        return len(outcomes) == 2 and {o.lower() for o in outcomes} == {'yes', 'no'}

    def _to_snapshot(self, item: dict) -> MarketSnapshot:
        outcome_prices = json.loads(item.get('outcomePrices') or '[]')
        yes_price = float(outcome_prices[0])
        no_price = float(outcome_prices[1])
        closes_at = None
        raw_end = item.get('endDate') or item.get('endDateIso')
        if raw_end:
            closes_at = datetime.fromisoformat(raw_end.replace('Z', '+00:00')).replace(tzinfo=None)
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
            volume_24h_usd=float(item.get('volume24hr') or item.get('volume24h') or item.get('volume24Hr') or 0),
            category=item.get('category') or 'general',
            event_key=item.get('slug') or str(item.get('id')),
            closes_at=closes_at,
            fetched_at=utcnow(),
        )
