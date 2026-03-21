from datetime import timedelta

from polyclaw.domain import MarketSnapshot
from polyclaw.timeutils import utcnow


class SampleMarketProvider:
    def list_markets(self, limit: int) -> list[MarketSnapshot]:
        now = utcnow()
        sample = [
            MarketSnapshot(
                market_id='pm-us-election-demo',
                title='Will candidate A win the demo election?',
                description='Deterministic demo market.',
                yes_price=0.41,
                no_price=0.61,
                spread_bps=180,
                liquidity_usd=25000,
                volume_24h_usd=7000,
                category='politics',
                event_key='demo-election-2026',
                closes_at=now + timedelta(days=20),
                fetched_at=now,
            ),
            MarketSnapshot(
                market_id='pm-fed-cut-demo',
                title='Will the Fed cut rates by next meeting?',
                description='Deterministic demo market.',
                yes_price=0.29,
                no_price=0.73,
                spread_bps=220,
                liquidity_usd=18000,
                volume_24h_usd=4500,
                category='macro',
                event_key='fed-cut-next-meeting-demo',
                closes_at=now + timedelta(days=14),
                fetched_at=now,
            ),
        ]
        return sample[:limit]
