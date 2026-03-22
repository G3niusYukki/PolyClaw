"""Performance Evaluator — evaluates whether the system meets scaling criteria."""

from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.models import ShadowResult
from polyclaw.safety import GlobalCircuitBreaker
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class PerformanceEvaluator:
    """
    Evaluates trading performance against scaling criteria.

    Checks four dimensions:
      1. Profitability: profitable for 2+ consecutive weeks
      2. Sharpe ratio: acceptable risk-adjusted returns
      3. Drawdown: within acceptable bounds
      4. Circuit breakers: no active circuit breakers
    """

    def __init__(
        self,
        profitable_weeks: int = 2,
        sharpe_threshold: float = 1.0,
        drawdown_threshold: float = 0.15,
    ):
        self.profitable_weeks = profitable_weeks
        self.sharpe_threshold = sharpe_threshold
        self.drawdown_threshold = drawdown_threshold
        self._breaker = GlobalCircuitBreaker()

    def is_profitable(self, session: 'Session', days: int = 14) -> bool:
        """
        Check if the system has been profitable over the specified period.

        Args:
            session: SQLAlchemy session
            days: Number of days to evaluate (default 14)

        Returns:
            True if cumulative PnL over the period is positive
        """
        from datetime import timedelta
        cutoff = utcnow() - timedelta(days=days)

        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
        )
        results = list(session.scalars(stmt).all())
        if not results:
            return False

        total_pnl = sum(r.pnl for r in results)
        return total_pnl > 0

    def sharpe_acceptable(self, session: 'Session', threshold: float | None = None) -> bool:
        """
        Check if the Sharpe ratio meets the threshold.

        Args:
            session: SQLAlchemy session
            threshold: Override threshold (defaults to self.sharpe_threshold)

        Returns:
            True if Sharpe ratio exceeds the threshold
        """
        threshold = threshold or self.sharpe_threshold
        sharpe = self._compute_sharpe(session)
        return sharpe is not None and sharpe > threshold

    def drawdown_acceptable(self, session: 'Session', threshold: float | None = None) -> bool:
        """
        Check if current drawdown is within the threshold.

        Args:
            session: SQLAlchemy session
            threshold: Override threshold (defaults to self.drawdown_threshold)

        Returns:
            True if drawdown <= threshold
        """
        threshold = threshold or self.drawdown_threshold
        drawdown = self._compute_drawdown(session)
        return drawdown <= threshold

    def no_active_circuit_breakers(self) -> bool:
        """
        Check if any circuit breakers are currently active.

        Returns:
            True if no circuit breakers are triggered
        """
        return not self._breaker.is_triggered()

    def get_all_criteria(self, session: 'Session') -> dict:
        """
        Evaluate all criteria and return a detailed status report.

        Args:
            session: SQLAlchemy session

        Returns:
            dict with:
              - profitable_14d: bool
              - sharpe_ratio: float | None
              - drawdown_pct: float | None
              - circuit_breakers_active: bool
              - all_criteria_met: bool
        """
        sharpe = self._compute_sharpe(session)
        drawdown = self._compute_drawdown(session)

        return {
            'profitable_14d': self.is_profitable(session),
            'sharpe_ratio': sharpe,
            'sharpe_threshold': self.sharpe_threshold,
            'drawdown_pct': drawdown,
            'drawdown_threshold': self.drawdown_threshold,
            'circuit_breakers_active': self._breaker.is_triggered(),
            'all_criteria_met': (
                self.is_profitable(session)
                and self.sharpe_acceptable(session)
                and self.drawdown_acceptable(session)
                and self.no_active_circuit_breakers()
            ),
        }

    def _compute_sharpe(self, session: 'Session', window_days: int = 30) -> float | None:
        """Compute Sharpe ratio from shadow results over the window."""
        from datetime import timedelta

        cutoff = utcnow() - timedelta(days=window_days)
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
        )
        results = list(session.scalars(stmt).all())
        if len(results) < 2:
            return None

        pnls = [r.pnl for r in results]
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / max(len(pnls) - 1, 1)
        std_dev = max(variance ** 0.5, 1e-9)
        # Annualized Sharpe (daily returns, 252 trading days)
        return round(mean_pnl / std_dev * (252 ** 0.5), 4)  # type: ignore[no-any-return]

    def _compute_drawdown(self, session: 'Session', window_days: int = 30) -> float:
        """Compute current drawdown from equity curve."""
        from datetime import timedelta

        cutoff = utcnow() - timedelta(days=window_days)
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
            .order_by(ShadowResult.resolved_at)
        )
        results = list(session.scalars(stmt).all())

        peak = 0.0
        current = 0.0
        for r in results:
            current += r.pnl
            if current > peak:
                peak = current

        if peak <= 0:
            return 0.0
        return round(max((peak - current) / peak, 0.0), 4)
