"""Market Whitelist — controls which markets are eligible for trading."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.models import MarketWhitelistRecord
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from polyclaw.domain import MarketSnapshot

# Default expand criteria thresholds
DEFAULT_MIN_LIQUIDITY_USD = 50_000.0  # $50K minimum liquidity
DEFAULT_MAX_SPREAD_BPS = 200  # 200 basis points maximum spread


@dataclass
class WhitelistCheck:
    """Result of a whitelist eligibility check."""
    allowed: bool
    reason: str
    source: str  # 'whitelist', 'expand', or 'blocked'


class MarketWhitelist:
    """
    Manages the list of markets eligible for trading.

    A market is allowed if:
      - It is explicitly on the whitelist, OR
      - It meets the expand criteria (liquidity > $50K, spread < 200 bps)

    Default state: all markets blocked until manually whitelisted.
    """

    def __init__(
        self,
        db_session: 'Session | None' = None,
        config: dict | None = None,
    ):
        self._session = db_session
        self._config = config or {}

        # Configurable thresholds (default if not provided)
        self.min_liquidity_usd = self._config.get(
            'min_liquidity_usd', DEFAULT_MIN_LIQUIDITY_USD
        )
        self.max_spread_bps = self._config.get(
            'max_spread_bps', DEFAULT_MAX_SPREAD_BPS
        )

    def _get_session(self) -> 'Session':
        if self._session is None:
            raise RuntimeError('No database session set on MarketWhitelist')
        return self._session

    def is_allowed(
        self,
        market_id: str,
        liquidity_usd: float | None = None,
        spread_bps: float | None = None,
    ) -> WhitelistCheck:
        """
        Check if a market is allowed for trading.

        Args:
            market_id: The market ID to check
            liquidity_usd: Optional liquidity from market snapshot
            spread_bps: Optional spread in basis points

        Returns:
            WhitelistCheck with allowed status, reason, and source
        """
        session = self._get_session()

        # Check explicit whitelist
        stmt = select(MarketWhitelistRecord).where(
            MarketWhitelistRecord.market_id == market_id
        )
        record = session.scalar(stmt)
        if record is not None:
            return WhitelistCheck(
                allowed=True,
                reason=f'market explicitly whitelisted at {record.added_at.isoformat()}',
                source='whitelist',
            )

        # Check expand criteria if market data is provided
        if liquidity_usd is not None and spread_bps is not None:
            if self._meets_expand_criteria(liquidity_usd, spread_bps):
                return WhitelistCheck(
                    allowed=True,
                    reason=f'meets expand criteria: liquidity=${liquidity_usd:.0f}, spread={spread_bps:.0f}bps',
                    source='expand',
                )

        return WhitelistCheck(
            allowed=False,
            reason='market not on whitelist and does not meet expand criteria',
            source='blocked',
        )

    def _meets_expand_criteria(self, liquidity_usd: float, spread_bps: float) -> bool:
        """Check if market meets the auto-expand criteria."""
        return bool(
            liquidity_usd >= self.min_liquidity_usd
            and spread_bps <= self.max_spread_bps
        )

    def get_whitelist(self) -> list[str]:
        """
        Get the list of whitelisted market IDs.

        Returns:
            List of market IDs on the whitelist
        """
        session = self._get_session()
        rows = session.scalars(
            select(MarketWhitelistRecord.market_id)
            .order_by(MarketWhitelistRecord.added_at.desc())
        ).all()
        return list(rows)

    def add_to_whitelist(
        self,
        market_id: str,
        reason: str = 'manual_add',
    ) -> bool:
        """
        Add a market to the whitelist.

        Returns True if added, False if already exists.
        """
        session = self._get_session()

        stmt = select(MarketWhitelistRecord).where(
            MarketWhitelistRecord.market_id == market_id
        )
        existing = session.scalar(stmt)
        if existing is not None:
            return False

        record = MarketWhitelistRecord(
            market_id=market_id,
            added_reason=reason,
            added_at=utcnow(),
        )
        session.add(record)
        session.commit()
        return True

    def remove_from_whitelist(self, market_id: str) -> bool:
        """
        Remove a market from the whitelist.

        Returns True if removed, False if not found.
        """
        session = self._get_session()

        stmt = select(MarketWhitelistRecord).where(
            MarketWhitelistRecord.market_id == market_id
        )
        record = session.scalar(stmt)
        if record is None:
            return False

        session.delete(record)
        session.commit()
        return True

    def sync_from_db(self, session: 'Session') -> None:
        """Sync the session reference from external call."""
        self._session = session

    def evaluate_expansion_candidates(
        self,
        markets: list['MarketSnapshot'],
    ) -> list[str]:
        """
        Evaluate a list of market snapshots and return IDs of expansion candidates.

        A market is an expansion candidate if it meets ALL of:
          - Liquidity > $50,000
          - Spread < 200 basis points
          - Volume > $10,000 in last 24h
          - Not already whitelisted

        Args:
            markets: List of MarketSnapshot objects to evaluate

        Returns:
            List of market IDs that qualify as expansion candidates
        """
        session = self._get_session()

        # Get already whitelisted IDs for quick lookup
        existing = set(self.get_whitelist())

        candidates = []
        for market in markets:
            if market.market_id in existing:
                continue
            if (
                market.liquidity_usd > 50_000.0
                and market.spread_bps < 200
                and market.volume_24h_usd > 10_000.0
            ):
                candidates.append(market.market_id)

        return candidates
