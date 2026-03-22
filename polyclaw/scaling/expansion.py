"""Market Expansion — suggests and applies market expansion based on liquidity and spread criteria."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.execution.whitelist import MarketWhitelist
from polyclaw.models import Market, MarketWhitelistRecord
from polyclaw.safety import log_event
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Expansion candidate thresholds
EXPANSION_MIN_LIQUIDITY_USD = 50_000.0
EXPANSION_MAX_SPREAD_BPS = 200
EXPANSION_MIN_VOLUME_USD = 10_000.0


@dataclass
class MarketExpansionSuggestion:
    """A suggested market for expansion to the whitelist."""
    market_id: str
    title: str
    liquidity_usd: float
    spread_bps: int
    volume_24h_usd: float
    category: str
    reason: str


class MarketExpander:
    """
    Manages market expansion by suggesting and applying new whitelist entries.

    Suggests markets that meet liquidity, spread, and volume criteria but are
    not yet on the whitelist. Apply expansion adds them to the whitelist
    and logs to the audit trail.
    """

    def __init__(
        self,
        whitelist: MarketWhitelist | None = None,
        min_liquidity_usd: float = EXPANSION_MIN_LIQUIDITY_USD,
        max_spread_bps: int = EXPANSION_MAX_SPREAD_BPS,
        min_volume_usd: float = EXPANSION_MIN_VOLUME_USD,
    ):
        self._whitelist = whitelist
        self.min_liquidity_usd = min_liquidity_usd
        self.max_spread_bps = max_spread_bps
        self.min_volume_usd = min_volume_usd

    def suggest_expansion(self, session: 'Session') -> list[MarketExpansionSuggestion]:
        """
        Suggest markets that meet expansion criteria but are not whitelisted.

        Criteria:
          - Liquidity > $50,000
          - Spread < 200 basis points
          - Volume > $10,000 in last 24h
          - Not already on the whitelist

        Returns:
            List of MarketExpansionSuggestion objects
        """
        # Get already whitelisted market IDs
        whitelist_ids = set(
            session.scalars(select(MarketWhitelistRecord.market_id)).all()
        )

        # Get all active markets not on whitelist
        stmt = (
            select(Market)
            .where(Market.is_active == True)  # noqa: E712
            .where(~Market.market_id.in_(whitelist_ids))
        )
        candidates = session.scalars(stmt).all()

        suggestions = []
        for market in candidates:
            if self._meets_expansion_criteria(market):
                suggestions.append(MarketExpansionSuggestion(
                    market_id=market.market_id,
                    title=market.title,
                    liquidity_usd=market.liquidity_usd,
                    spread_bps=market.spread_bps,
                    volume_24h_usd=market.volume_24h_usd,
                    category=market.category or 'general',
                    reason=(
                        f'liquidity=${market.liquidity_usd:.0f} > ${self.min_liquidity_usd:.0f}, '
                        f'spread={market.spread_bps}bps < {self.max_spread_bps}bps, '
                        f'volume=${market.volume_24h_usd:.0f} > ${self.min_volume_usd:.0f}'
                    ),
                ))

        return suggestions

    def apply_expansion(self, session: 'Session', market_id: str) -> bool:
        """
        Add a market to the whitelist and log to audit trail.

        Args:
            session: SQLAlchemy session
            market_id: The market ID to add

        Returns:
            True if added successfully, False if already exists
        """
        whitelist = self._get_whitelist(session)
        added = whitelist.add_to_whitelist(
            market_id=market_id,
            reason=f'expansion_criteria_met|liquidity=${self.min_liquidity_usd:.0f}|spread<{self.max_spread_bps}bps',
        )

        if added:
            log_event(
                session,
                'market_expansion_applied',
                f'market_id={market_id}|min_liquidity=${self.min_liquidity_usd:.0f}',
                'ok',
            )
            session.commit()

        return added

    def _meets_expansion_criteria(self, market: Market) -> bool:
        """Check if a market meets all expansion criteria."""
        return (
            market.liquidity_usd >= self.min_liquidity_usd
            and market.spread_bps <= self.max_spread_bps
            and market.volume_24h_usd >= self.min_volume_usd
        )

    def _get_whitelist(self, session: 'Session') -> MarketWhitelist:
        """Get or create the whitelist with the session."""
        if self._whitelist is None:
            self._whitelist = MarketWhitelist(db_session=session)
        else:
            self._whitelist.sync_from_db(session)
        return self._whitelist
