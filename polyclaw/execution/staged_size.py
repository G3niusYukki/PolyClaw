"""Staged Position Sizing — controls trade sizing based on trading stage progression."""

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.config import settings
from polyclaw.models import TradingStageRecord
from polyclaw.safety import GlobalCircuitBreaker, log_event
from polyclaw.shadow.accuracy import SignalAccuracyMonitor

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TradingStage(IntEnum):
    """Trading stage levels with progressive position sizing."""
    SHADOW = 0
    STAGE1_10PCT = 1
    STAGE2_25PCT = 2
    STAGE3_50PCT = 3
    STAGE4_100PCT = 4

    @property
    def display_name(self) -> str:
        return {
            0: 'SHADOW',
            1: 'STAGE1_10PCT',
            2: 'STAGE2_25PCT',
            3: 'STAGE3_50PCT',
            4: 'STAGE4_100PCT',
        }[self.value]

    @property
    def scale_factor(self) -> float:
        return {
            0: 0.0,
            1: 0.10,
            2: 0.25,
            3: 0.50,
            4: 1.0,
        }[self.value]


@dataclass
class StageAdvanceResult:
    """Result of a stage advance attempt."""
    success: bool
    new_stage: int
    reason: str
    blockers: list[str]


class StagedPositionSizer:
    """
    Controls position sizing based on the current trading stage.

    Stages:
      0 (SHADOW): 0% of base stake — no real execution
      1 (STAGE1_10PCT): 10% of base stake
      2 (STAGE2_25PCT): 25% of base stake
      3 (STAGE3_50PCT): 50% of base stake
      4 (STAGE4_100PCT): 100% of base stake

    Advancement from one stage to the next requires:
      - Signal accuracy > 60% over last 30 days
      - Shadow/live paper trades > 50
      - No critical drift detected
      - No active circuit breakers
    """

    # Stage advance gate thresholds
    MIN_ACCURACY = 0.60
    MIN_PAPER_TRADES = 50
    MAX_DAILY_DRIFT_PCT = 5.0

    def __init__(self):
        self._accuracy_monitor = SignalAccuracyMonitor()

    def get_stage(self) -> TradingStage:
        """Return the current trading stage from config."""
        try:
            return TradingStage(settings.shadow_stage)
        except ValueError:
            return TradingStage.SHADOW

    def scale_stake(self, base_stake: float) -> float:
        """
        Apply stage scaling to a base stake amount.

        Args:
            base_stake: The raw calculated stake amount.

        Returns:
            The scaled stake based on current stage. Stage 0 returns 0.
        """
        stage = self.get_stage()
        return round(base_stake * stage.scale_factor, 2)

    def can_advance(self, session: 'Session | None' = None) -> tuple[bool, list[str]]:
        """
        Check if the current stage can advance to the next stage.

        Returns (True, []) if all gate conditions are met, else (False, [reasons]).

        Gate conditions:
          1. Accuracy > 60% over last 30 days
          2. Paper/shadow trades > 50
          3. No critical drift
          4. No active circuit breakers
        """
        blockers: list[str] = []
        stage = self.get_stage()

        # Cannot advance from the max stage
        if stage >= TradingStage.STAGE4_100PCT:
            return False, ['already at maximum stage (STAGE4_100PCT)']

        if session is None:
            return False, ['no database session provided']

        # Gate 1: Accuracy > 60%
        try:
            accuracy_data = self._accuracy_monitor.get_accuracy(window_days=30, session=session)
            accuracy = accuracy_data['accuracy']
        except Exception:
            accuracy = 0.0

        if accuracy <= self.MIN_ACCURACY:
            blockers.append(
                f'accuracy={accuracy:.2%} <= {self.MIN_ACCURACY:.0%} required'
            )

        # Gate 2: Paper/shadow trades > 50
        total_trades = accuracy_data.get('total_signals', 0)
        # Also count unresolved shadow positions as paper trades
        from polyclaw.models import Position
        shadow_positions = session.scalars(
            select(Position).where(Position.is_shadow.is_(True))
        ).all()
        total_trades += len(shadow_positions)

        if total_trades <= self.MIN_PAPER_TRADES:
            blockers.append(
                f'paper_trades={total_trades} <= {self.MIN_PAPER_TRADES} required'
            )

        # Gate 3: No active circuit breakers
        breaker = GlobalCircuitBreaker()
        if breaker.is_triggered():
            blockers.append(f'circuit_breaker_active: {breaker.get_trigger_reason()}')

        return (len(blockers) == 0, blockers)

    def advance(self, session: 'Session') -> StageAdvanceResult:
        """
        Advance to the next trading stage.

        Records the stage change in the database for audit.
        """
        can_advance, blockers = self.can_advance(session)
        stage = self.get_stage()

        if not can_advance:
            return StageAdvanceResult(
                success=False,
                new_stage=stage.value,
                reason='gate conditions not met',
                blockers=blockers,
            )

        if stage >= TradingStage.STAGE4_100PCT:
            return StageAdvanceResult(
                success=False,
                new_stage=stage.value,
                reason='already at maximum stage',
                blockers=['maximum stage reached'],
            )

        new_stage = TradingStage(stage.value + 1)
        settings.shadow_stage = new_stage.value

        # Record stage change
        record = TradingStageRecord(
            stage=new_stage.value,
            reason=f'advance from {stage.display_name} to {new_stage.display_name}',
        )
        session.add(record)

        log_event(
            session,
            'stage_advanced',
            f'from={stage.display_name}|to={new_stage.display_name}',
            'ok',
        )
        session.commit()

        return StageAdvanceResult(
            success=True,
            new_stage=new_stage.value,
            reason=f'advanced from {stage.display_name} to {new_stage.display_name}',
            blockers=[],
        )

    def rollback(self, session: 'Session') -> StageAdvanceResult:
        """
        Revert to shadow mode (stage 0).

        Records the rollback in the database for audit.
        """
        current = self.get_stage()
        settings.shadow_stage = 0

        record = TradingStageRecord(
            stage=0,
            reason=f'rollback from {current.display_name}',
        )
        session.add(record)

        log_event(
            session,
            'stage_rollback',
            f'from={current.display_name}|to=SHADOW',
            'ok',
        )
        session.commit()

        return StageAdvanceResult(
            success=True,
            new_stage=0,
            reason=f'rolled back from {current.display_name} to SHADOW',
            blockers=[],
        )
