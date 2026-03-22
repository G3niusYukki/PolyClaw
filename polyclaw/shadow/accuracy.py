"""Signal Accuracy Monitoring — tracks shadow trading accuracy over time."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.models import Position, ShadowResult
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ShadowResultRecord:
    """Dataclass for shadow trading result data (returned from DB queries)."""
    market_id: str
    strategy_id: str
    predicted_side: str
    predicted_prob: float
    shadow_fill_price: float
    actual_outcome: str
    pnl: float
    accuracy: bool
    resolved_at: datetime | None


class SignalAccuracyMonitor:
    """
    Monitors signal accuracy based on shadow trading results.

    Records resolution events when markets resolve, calculates accuracy
    metrics over a configurable rolling window, and aggregates per-strategy.
    """

    def update(
        self,
        market_id: str,
        predicted_side: str,
        actual_outcome: str,
        session: 'Session',
    ) -> ShadowResultRecord | None:
        """
        Record a market resolution event and update matching shadow positions.

        When a market resolves, this marks all unresolved shadow results for
        that market as resolved, calculates accuracy, and stores the outcome.

        Args:
            market_id: The resolved market ID
            predicted_side: The side that was predicted ('yes' or 'no')
            actual_outcome: The actual market outcome ('yes' or 'no')
            session: SQLAlchemy session

        Returns:
            The updated ShadowResultRecord, or None if no matching result found
        """
        # Find unresolved shadow results for this market
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.market_id == market_id)
            .where(ShadowResult.actual_outcome == '')
        )
        results = session.scalars(stmt).all()

        if not results:
            return None

        now = utcnow()

        for result in results:
            result.actual_outcome = actual_outcome
            result.resolved_at = now

            # Calculate accuracy: prediction matches outcome
            is_correct = result.predicted_side == actual_outcome
            result.accuracy = is_correct

            # Calculate PnL
            if actual_outcome == 'yes':
                # YES position: if predicted YES, PnL = (1.0 - fill_price) * qty
                if result.predicted_side == 'yes':
                    result.pnl = round((1.0 - result.shadow_fill_price) * 1.0, 4)
            elif actual_outcome == 'no':
                # NO position: if predicted NO, PnL = (1.0 - fill_price) * qty
                # (NO pays 1.0 - no_price on a YES bet)
                if result.predicted_side == 'no':
                    result.pnl = round((1.0 - result.shadow_fill_price) * 1.0, 4)

            # Mark corresponding shadow position as resolved
            pos_stmt = (
                select(Position)
                .where(Position.market_id == market_id)
                .where(Position.is_shadow.is_(True))
                .where(Position.is_open.is_(True))
            )
            shadow_pos = session.scalar(pos_stmt)
            if shadow_pos:
                shadow_pos.is_open = False

        session.commit()

        return ShadowResultRecord(
            market_id=market_id,
            strategy_id=results[0].strategy_id,
            predicted_side=results[0].predicted_side,
            predicted_prob=results[0].predicted_prob,
            shadow_fill_price=results[0].shadow_fill_price,
            actual_outcome=actual_outcome,
            pnl=results[0].pnl,
            accuracy=results[0].accuracy,
            resolved_at=now,
        )

    def get_accuracy(self, window_days: int = 30, session: 'Session | None' = None) -> dict:
        """
        Calculate signal accuracy over a rolling window.

        Args:
            window_days: Number of days to look back (default 30)
            session: Optional SQLAlchemy session for DB queries

        Returns:
            dict with:
              - accuracy: overall accuracy ratio (0.0 to 1.0)
              - total_signals: total resolved signals in window
              - correct_signals: number of correct predictions
              - by_strategy: {strategy_id: accuracy} for each strategy
              - total_pnl: cumulative PnL from shadow trades
        """
        if session is None:
            return {
                'accuracy': 0.0,
                'total_signals': 0,
                'correct_signals': 0,
                'by_strategy': {},
                'total_pnl': 0.0,
            }

        cutoff = utcnow() - timedelta(days=window_days)

        # Get all resolved shadow results within the window
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
        )
        results = session.scalars(stmt).all()

        total = len(results)
        if total == 0:
            return {
                'accuracy': 0.0,
                'total_signals': 0,
                'correct_signals': 0,
                'by_strategy': {},
                'total_pnl': 0.0,
            }

        correct = sum(1 for r in results if r.accuracy)
        total_pnl = sum(r.pnl for r in results)

        # Aggregate by strategy
        by_strategy: dict[str, dict] = {}
        for r in results:
            if r.strategy_id not in by_strategy:
                by_strategy[r.strategy_id] = {'total': 0, 'correct': 0, 'pnl': 0.0}
            by_strategy[r.strategy_id]['total'] += 1
            if r.accuracy:
                by_strategy[r.strategy_id]['correct'] += 1
            by_strategy[r.strategy_id]['pnl'] += r.pnl

        # Convert to accuracy per strategy
        strategy_accuracy = {}
        for sid, data in by_strategy.items():
            strategy_accuracy[sid] = round(data['correct'] / data['total'], 4) if data['total'] > 0 else 0.0

        return {
            'accuracy': round(correct / total, 4),
            'total_signals': total,
            'correct_signals': correct,
            'by_strategy': strategy_accuracy,
            'total_pnl': round(total_pnl, 4),
        }
