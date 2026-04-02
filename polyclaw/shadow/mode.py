"""Shadow Mode Engine — simulates order execution without real submission."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from polyclaw.domain import MarketSnapshot
from polyclaw.models import Position, ShadowResult
from polyclaw.repositories import upsert_market
from polyclaw.safety import log_event
from polyclaw.strategies.base import Signal
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ShadowPosition:
    """Represents a simulated (shadow) trading position."""
    market_id: str
    side: str
    quantity: float
    entry_price: float
    shadow_fill_price: float
    shadow_fill_time: datetime
    status: str = 'open'
    strategy_id: str = ''
    pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'side': self.side,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'shadow_fill_price': self.shadow_fill_price,
            'shadow_fill_time': self.shadow_fill_time.isoformat(),
            'status': self.status,
            'strategy_id': self.strategy_id,
            'pnl': self.pnl,
        }


class ShadowModeEngine:
    """
    Shadow Mode Engine — processes signals in simulation mode without submitting real orders.

    Calculates shadow fill prices using market mid prices from snapshots,
    stores shadow positions in the DB, and tracks shadow PnL.
    """

    def __init__(self):
        self._positions: list[ShadowPosition] = []

    @property
    def positions(self) -> list[ShadowPosition]:
        return self._positions

    def get_mid_price(self, market) -> float:
        """Return the mid price (average of yes and no prices) for a market.

        Works with both MarketSnapshot (domain) and Market (ORM) models.
        """
        # MarketSnapshot: yes_price / no_price
        # Market ORM: outcome_yes_price / outcome_no_price
        yes_price: float = getattr(market, 'yes_price', None) or getattr(market, 'outcome_yes_price', 0.0)  # type: ignore[assignment]
        no_price: float = getattr(market, 'no_price', None) or getattr(market, 'outcome_no_price', 0.0)  # type: ignore[assignment]
        return round((yes_price + no_price) / 2.0, 4)

    def calculate_shadow_fill_price(self, market, side: str, order_size_usd: float = 10.0) -> float:
        """
        Calculate the shadow fill price for a given market and side.

        Uses the market mid price plus a slippage estimate based on order size
        relative to available liquidity.

        Args:
            market: MarketSnapshot or Market ORM object.
            side: 'yes' or 'no'.
            order_size_usd: Estimated order size in USD (used for slippage calc).

        Returns:
            Simulated fill price including slippage.
        """
        mid = self.get_mid_price(market)

        # Estimate slippage based on order size vs liquidity
        liquidity: float = getattr(market, 'liquidity_usd', 0.0)
        if liquidity <= 0:
            # No liquidity info — use conservative slippage
            slippage_pct = 0.005  # 0.5%
        else:
            # Slippage increases with order size relative to liquidity
            # Cap at 0.5% max
            slippage_pct = min(0.005, order_size_usd / liquidity)

        # Apply slippage: buying YES pushes price up, buying NO pushes it down
        if side == 'yes':
            return round(mid * (1 + slippage_pct), 4)
        else:
            return round(mid * (1 - slippage_pct), 4)

    def calculate_pnl(self, shadow_pos: ShadowPosition, outcome_price: float) -> float:
        """
        Calculate shadow PnL given the actual outcome price.

        PnL is calculated as: (exit_price - entry_price) * quantity for 'yes' side,
        or (entry_price - exit_price) * quantity for 'no' side.
        """
        if shadow_pos.side == 'yes':
            return round((outcome_price - shadow_pos.shadow_fill_price) * shadow_pos.quantity, 4)
        elif shadow_pos.side == 'no':
            return round((shadow_pos.shadow_fill_price - outcome_price) * shadow_pos.quantity, 4)
        return 0.0

    def resolve_position(self, market_id: str, outcome_price: float) -> ShadowPosition | None:
        """Resolve a shadow position by marking it closed and calculating PnL."""
        for pos in self._positions:
            if pos.market_id == market_id and pos.status == 'open':
                pos.pnl = self.calculate_pnl(pos, outcome_price)
                pos.status = 'resolved'
                return pos
        return None

    def add_position(self, pos: ShadowPosition) -> None:
        """Add a new shadow position."""
        self._positions.append(pos)

    def reset(self) -> None:
        """Clear all shadow positions."""
        self._positions.clear()


def process_shadow_signals(
    signals: list[Signal],
    market_data: list[MarketSnapshot],
    session: 'Session',
) -> list[ShadowPosition]:
    """
    Process a list of trading signals in shadow mode (no real order submission).

    For each signal:
    1. Match it to the corresponding market snapshot
    2. Calculate the shadow fill price (mid price)
    3. Create a shadow position record in the DB (is_shadow=True)
    4. Create a shadow result record for accuracy tracking

    Args:
        signals: List of Signal objects from strategies
        market_data: List of MarketSnapshot objects for the same markets
        session: SQLAlchemy session for DB operations

    Returns:
        List of ShadowPosition objects created
    """
    engine = ShadowModeEngine()

    # Build a lookup map for market data
    market_map: dict[str, MarketSnapshot] = {m.market_id: m for m in market_data}

    created_positions: list[ShadowPosition] = []

    for signal in signals:
        market = market_map.get(signal.market_id)
        if market is None:
            log_event(
                session,
                'shadow_skip',
                f'no market snapshot for signal market_id={signal.market_id}',
                'skipped',
            )
            continue

        # Calculate shadow fill price with slippage model
        shadow_fill_price = engine.calculate_shadow_fill_price(
            market,
            signal.side.value if hasattr(signal.side, 'value') else signal.side,
            order_size_usd=signal.stake_usd,
        )

        # Calculate quantity from stake and price
        side_str = signal.side.value if hasattr(signal.side, 'value') else signal.side
        price_for_qty = market.yes_price if side_str == 'yes' else market.no_price
        quantity = round(signal.stake_usd / max(price_for_qty, 0.01), 4)

        now = utcnow()

        # Create ShadowPosition dataclass
        shadow_pos = ShadowPosition(
            market_id=signal.market_id,
            side=side_str,
            quantity=quantity,
            entry_price=price_for_qty,
            shadow_fill_price=shadow_fill_price,
            shadow_fill_time=now,
            status='open',
            strategy_id=signal.strategy_id,
            pnl=0.0,
        )

        # Upsert market record if needed
        market_record = upsert_market(session, market)

        # Store shadow position in DB with is_shadow=True
        db_position = Position(
            event_key=market.event_key,
            market_id=market.market_id,
            side=side_str,
            notional_usd=signal.stake_usd,
            avg_price=shadow_fill_price,
            quantity=quantity,
            opened_at=now,
            is_open=True,
            is_shadow=True,
            strategy_id=signal.strategy_id,
        )
        session.add(db_position)

        # Create shadow result record for accuracy tracking
        shadow_result = ShadowResult(
            market_id=market.market_id,
            strategy_id=signal.strategy_id,
            predicted_side=side_str,
            predicted_prob=signal.confidence,
            shadow_fill_price=shadow_fill_price,
            actual_outcome='',
            pnl=0.0,
            accuracy=False,
            resolved_at=None,
            created_at=now,
        )
        session.add(shadow_result)

        # Track in memory
        engine.add_position(shadow_pos)
        created_positions.append(shadow_pos)

        log_event(
            session,
            'shadow_position_created',
            f'market_id={market.market_id}|side={side_str}|strategy={signal.strategy_id}|fill_price={shadow_fill_price}',
            'ok',
        )

    session.commit()
    return created_positions
