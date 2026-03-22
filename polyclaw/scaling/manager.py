"""Scaling Manager — orchestrates stage advancement based on performance criteria."""

from typing import TYPE_CHECKING

from polyclaw.execution.staged_size import StagedPositionSizer, TradingStage
from polyclaw.scaling.evaluator import PerformanceEvaluator

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ScalingManager:
    """
    Manages trading stage scaling based on performance evaluation.

    The ScalingManager coordinates with StagedPositionSizer to advance
    or rollback trading stages based on whether performance criteria are met.

    Scaling criteria:
      - Profitable for 2+ weeks (cumulative PnL > 0)
      - Sharpe ratio > 1.0
      - Drawdown < 15%
      - No active circuit breakers

    Backward scaling (rollback) is triggered automatically when:
      - Drawdown exceeds 15%
      - Sharpe ratio drops below 0.5
      - Circuit breaker triggers
    """

    def __init__(
        self,
        evaluator: PerformanceEvaluator | None = None,
        sizer: StagedPositionSizer | None = None,
    ):
        self._evaluator = evaluator or PerformanceEvaluator()
        self._sizer = sizer or StagedPositionSizer()

    def get_current_stage(self) -> int:
        """
        Get the current trading stage.

        Returns:
            Integer stage (0=SHADOW, 1=10%, 2=25%, 3=50%, 4=100%)
        """
        return self._sizer.get_stage().value

    def evaluate_scale(self, session: 'Session | None' = None) -> tuple[bool, str]:
        """
        Evaluate whether the system is ready to scale to the next stage.

        Args:
            session: SQLAlchemy session (required for performance checks)

        Returns:
            tuple of (ready_to_scale: bool, reason: str)
        """
        if session is None:
            return False, 'no database session provided'

        criteria = self._evaluator.get_all_criteria(session)
        stage = self._sizer.get_stage()

        # Check if already at max stage
        if stage >= TradingStage.STAGE4_100PCT:
            return False, f'already at maximum stage (STAGE4_100PCT / 100%)'

        # Check all criteria
        blockers = []
        if not criteria['profitable_14d']:
            blockers.append(f'not profitable over 14d')
        if criteria['sharpe_ratio'] is not None and criteria['sharpe_ratio'] <= self._evaluator.sharpe_threshold:
            blockers.append(f'Sharpe={criteria["sharpe_ratio"]:.2f} <= {self._evaluator.sharpe_threshold}')
        if criteria['drawdown_pct'] > self._evaluator.drawdown_threshold:
            blockers.append(f'drawdown={criteria["drawdown_pct"]:.1%} > {self._evaluator.drawdown_threshold:.1%}')
        if criteria['circuit_breakers_active']:
            blockers.append('circuit breaker active')

        if blockers:
            return False, f'criteria not met: {"; ".join(blockers)}'

        return True, f'all criteria met (Sharpe={criteria["sharpe_ratio"]:.2f}, DD={criteria["drawdown_pct"]:.1%})'

    def scale_to(self, session: 'Session', target_stage: int) -> dict:
        """
        Scale to a specific trading stage.

        Args:
            session: SQLAlchemy session
            target_stage: Target stage number (0-4)

        Returns:
            dict with success status, new_stage, and blockers
        """
        # Validate target stage
        try:
            target = TradingStage(target_stage)
        except ValueError:
            return {
                'success': False,
                'new_stage': self.get_current_stage(),
                'reason': f'invalid stage: {target_stage}',
                'blockers': [f'target_stage must be 0-4, got {target_stage}'],
            }

        current = self._sizer.get_stage()
        if current.value == target_stage:
            return {
                'success': True,
                'new_stage': target_stage,
                'reason': f'already at stage {target_stage}',
                'blockers': [],
            }

        # If scaling up, check criteria first
        if target.value > current.value:
            ready, reason = self.evaluate_scale(session)
            if not ready:
                return {
                    'success': False,
                    'new_stage': current.value,
                    'reason': 'criteria not met for scale-up',
                    'blockers': [reason],
                }

        # Perform the scale
        if target.value > current.value:
            result = self._sizer.advance(session)
            return {
                'success': result.success,
                'new_stage': result.new_stage,
                'reason': result.reason,
                'blockers': result.blockers,
            }
        elif target.value < current.value:
            result = self._sizer.rollback(session)
            return {
                'success': True,
                'new_stage': 0,
                'reason': f'rolled back from stage {current.value} to SHADOW',
                'blockers': [],
            }
        else:
            return {
                'success': True,
                'new_stage': current.value,
                'reason': 'no change needed',
                'blockers': [],
            }

    def auto_evaluate(self, session: 'Session') -> dict:
        """
        Automatically evaluate and apply scaling decisions.

        If criteria are met and not at max stage, attempts to advance.
        If circuit breaker triggers or drawdown exceeds threshold, rolls back.

        Args:
            session: SQLAlchemy session

        Returns:
            dict with the scaling decision and results
        """
        criteria = self._evaluator.get_all_criteria(session)
        current = self.get_current_stage()

        # Auto-rollback conditions
        if criteria['circuit_breakers_active']:
            return self.scale_to(session, 0)

        if criteria['drawdown_pct'] > self._evaluator.drawdown_threshold:
            return self.scale_to(session, 0)

        # Auto-advance if criteria met
        if criteria['all_criteria_met'] and current < TradingStage.STAGE4_100PCT.value:
            return self.scale_to(session, current + 1)

        return {
            'success': True,
            'new_stage': current,
            'reason': 'no scaling action needed',
            'criteria': criteria,
        }
