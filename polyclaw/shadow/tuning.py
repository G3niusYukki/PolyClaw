"""Confidence Threshold Tuning — suggests and analyzes optimal signal confidence thresholds."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.models import ShadowResult
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ThresholdSuggestion:
    """Result of threshold tuning analysis."""
    suggested_threshold: float
    current_threshold: float
    analysis_window: int
    sample_size: int


class ThresholdTuner:
    """
    Analyzes historical shadow results to suggest optimal confidence thresholds.

    Uses binary search to find the minimum confidence threshold that achieves
    the target accuracy, and provides impact analysis for any given threshold.
    """

    def suggest_threshold(
        self,
        strategy_id: str,
        session: 'Session',
        target_accuracy: float = 0.60,
        analysis_window_days: int = 30,
    ) -> ThresholdSuggestion:
        """
        Suggest a minimum confidence threshold for a strategy.

        Uses binary search on the confidence threshold to find the minimum
        passing threshold that achieves target_accuracy on historical data.

        Args:
            strategy_id: The strategy to analyze
            session: SQLAlchemy session
            target_accuracy: Target accuracy rate (default 0.60 = 60%)
            analysis_window_days: How many days of history to analyze (default 30)

        Returns:
            ThresholdSuggestion with the recommended threshold
        """
        from polyclaw.config import settings

        cutoff = utcnow() - timedelta(days=analysis_window_days)
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.strategy_id == strategy_id)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
        )
        results = list(session.scalars(stmt).all())
        sample_size = len(results)

        if sample_size == 0:
            return ThresholdSuggestion(
                suggested_threshold=settings.min_confidence,
                current_threshold=settings.min_confidence,
                analysis_window=analysis_window_days,
                sample_size=0,
            )

        # Build sorted list of confidence values
        conf_values = sorted([r.predicted_prob for r in results])

        # Binary search for minimum threshold achieving target_accuracy
        def accuracy_at_threshold(threshold: float) -> float:
            passed = [r for r in results if r.predicted_prob >= threshold]
            if not passed:
                return 0.0
            correct = sum(1 for r in passed if r.accuracy)
            return correct / len(passed)

        # Search range: 0.0 to 1.0
        lo, hi = 0.0, 1.0
        for _ in range(20):  # 20 iterations of binary search for precision
            mid = (lo + hi) / 2
            acc = accuracy_at_threshold(mid)
            if acc >= target_accuracy:
                hi = mid
            else:
                lo = mid

        suggested = round(hi, 4)

        return ThresholdSuggestion(
            suggested_threshold=suggested,
            current_threshold=settings.min_confidence,
            analysis_window=analysis_window_days,
            sample_size=sample_size,
        )

    def analyze_threshold_impact(
        self,
        strategy_id: str,
        threshold: float,
        session: 'Session',
        window_days: int = 30,
    ) -> dict:
        """
        Analyze the impact of applying a given confidence threshold.

        Args:
            strategy_id: The strategy to analyze
            threshold: The confidence threshold to evaluate
            session: SQLAlchemy session
            window_days: How many days of history (default 30)

        Returns:
            dict with:
              - threshold: the threshold being evaluated
              - signals_passed: how many signals pass this threshold
              - accuracy: accuracy of passed signals
              - pnl: cumulative PnL of passed signals
              - total_in_window: total signals in the analysis window
              - pass_rate: fraction of signals that pass this threshold
        """
        cutoff = utcnow() - timedelta(days=window_days)
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.strategy_id == strategy_id)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
        )
        all_results = list(session.scalars(stmt).all())

        total = len(all_results)
        passed = [r for r in all_results if r.predicted_prob >= threshold]
        passed_count = len(passed)

        if passed_count == 0:
            return {
                'threshold': threshold,
                'signals_passed': 0,
                'accuracy': 0.0,
                'pnl': 0.0,
                'total_in_window': total,
                'pass_rate': 0.0,
            }

        correct = sum(1 for r in passed if r.accuracy)
        total_pnl = sum(r.pnl for r in passed)

        return {
            'threshold': threshold,
            'signals_passed': passed_count,
            'accuracy': round(correct / passed_count, 4),
            'pnl': round(total_pnl, 4),
            'total_in_window': total,
            'pass_rate': round(passed_count / total, 4) if total > 0 else 0.0,
        }
