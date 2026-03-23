import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.timeutils import utcnow


class PolymarketGammaProvider:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url or settings.polymarket_gamma_url
        self._api_key = api_key or getattr(settings, 'polymarket_api_key', '')

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

    def get_positions(self) -> list[dict]:
        """
        Fetch the authenticated user's positions from the Polymarket Gamma REST API.

        Returns:
            List of position dicts, each containing at minimum:
            market_id, side, size, value, avg_price.
        """
        import logging
        logger = logging.getLogger(__name__)

        positions_url = getattr(settings, 'polymarket_positions_url', None)
        if not positions_url:
            logger.debug("polymarket_positions_url not configured; returning empty positions")
            return []

        try:
            req = Request(
                positions_url,
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                },
            )
            if self._api_key:
                req.add_header('Authorization', f'Bearer {self._api_key}')

            with urlopen(req, timeout=settings.request_timeout_seconds) as resp:
                payload = json.loads(resp.read().decode('utf-8'))

            raw_positions = payload if isinstance(payload, list) else payload.get('positions', [])
            return [
                {
                    'market_id': p.get('market_id', ''),
                    'side': p.get('side', 'yes'),
                    'size': float(p.get('size', 0.0)),
                    'value': float(p.get('value', 0.0)),
                    'avg_price': float(p.get('avgPrice', 0.0)),
                }
                for p in raw_positions
                if p.get('market_id')
            ]
        except Exception as exc:
            logger.warning("Failed to fetch positions from Polymarket Gamma API: %s", exc)
            return []

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
