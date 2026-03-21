from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.domain import DecisionProposal, MarketSnapshot
from polyclaw.models import Position
from polyclaw.timeutils import utcnow


class RiskEngine:
    def evaluate(self, session: Session, market: MarketSnapshot, proposal: DecisionProposal) -> tuple[bool, list[str]]:
        flags: list[str] = []

        if market.spread_bps > settings.max_spread_bps:
            flags.append('spread_too_wide')
        if market.liquidity_usd < settings.min_liquidity_usd:
            flags.append('liquidity_too_low')
        if market.fetched_at < utcnow() - timedelta(minutes=settings.max_market_age_minutes):
            flags.append('stale_market_data')

        open_positions = session.scalars(select(Position).where(Position.is_open.is_(True))).all()
        current_exposure = sum(p.notional_usd for p in open_positions)
        if current_exposure + proposal.stake_usd > settings.max_total_exposure_usd:
            flags.append('portfolio_exposure_limit')

        same_event_exposure = sum(p.notional_usd for p in open_positions if p.event_key == market.event_key)
        if same_event_exposure + proposal.stake_usd > settings.max_position_usd:
            flags.append('event_exposure_limit')

        if settings.execution_mode == 'live' and not settings.live_trading_enabled:
            flags.append('live_trading_disabled')

        return (len(flags) == 0, flags)
