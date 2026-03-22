"""Live Transition Manager — governs the transition from shadow to live trading."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.config import settings
from polyclaw.models import Position, ShadowResult, TradingStageRecord
from polyclaw.safety import GlobalCircuitBreaker, log_event
from polyclaw.shadow.accuracy import SignalAccuracyMonitor
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class GateStatus:
    """Status of a single transition gate criterion."""
    name: str
    passed: bool
    value: float | int | bool
    threshold: float | int


@dataclass
class TransitionStatus:
    """Overall transition manager status."""
    mode: str  # 'shadow' or 'live'
    current_stage: int
    live_enabled: bool
    gate_status: list[GateStatus]
    all_gates_passed: bool
    blocking_reasons: list[str]


class LiveTransitionManager:
    """
    Manages the transition from shadow mode to live trading.

    Validates all gate criteria before allowing live trading:
    - Signal accuracy > 60% over last 30 days
    - Shadow trades > 100
    - Reconciliation error < 1%
    - No active circuit breakers

    All transitions are logged to the audit log.
    """

    def __init__(self):
        self._live_enabled: bool = False
        self._accuracy_monitor = SignalAccuracyMonitor()

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled

    def can_go_live(self, session: 'Session') -> tuple[bool, list[str]]:
        """
        Check all gate criteria for going live.

        Returns (True, []) if all gates pass, or (False, [reasons]) if any fail.
        """
        gates: list[GateStatus] = []
        failures: list[str] = []

        # Gate 1: Signal accuracy > 60% over last 30 days
        try:
            accuracy_data = self._accuracy_monitor.get_accuracy(window_days=30, session=session)
            accuracy = accuracy_data['accuracy']
            total_signals = accuracy_data['total_signals']
        except Exception:
            accuracy = 0.0
            total_signals = 0

        gate_acc = GateStatus(
            name='signal_accuracy',
            passed=accuracy > 0.60,
            value=accuracy,
            threshold=0.60,
        )
        gates.append(gate_acc)
        if not gate_acc.passed:
            failures.append(
                f'signal_accuracy={accuracy:.2%} <= 60% (signals={total_signals})'
            )

        # Gate 2: Shadow trades > 100
        cutoff = utcnow() - timedelta(days=30)
        stmt = select(ShadowResult).where(ShadowResult.resolved_at >= cutoff)
        resolved_count = len(list(session.scalars(stmt).all()))

        gate_trades = GateStatus(
            name='shadow_trades_count',
            passed=resolved_count > 100,
            value=resolved_count,
            threshold=100,
        )
        gates.append(gate_trades)
        if not gate_trades.passed:
            failures.append(f'shadow_trades={resolved_count} <= 100')

        # Gate 3: Reconciliation error < 1%
        # Check that shadow positions are properly tracked (no reconciliation issues)
        # A reconciliation error is detected when a shadow position has no matching signal
        # For simplicity, we check if there are unresolved shadow positions older than 7 days
        old_cutoff = utcnow() - timedelta(days=7)
        stale_stmt = (
            select(Position)
            .where(Position.is_shadow.is_(True))
            .where(Position.is_open.is_(True))
            .where(Position.opened_at < old_cutoff)
        )
        stale_positions = len(list(session.scalars(stale_stmt).all()))

        # Reconciliation error rate = stale positions / total shadow positions
        all_shadow_stmt = select(Position).where(Position.is_shadow.is_(True))
        all_shadow = list(session.scalars(all_shadow_stmt).all())
        total_shadow = len(all_shadow)
        recon_error = stale_positions / total_shadow if total_shadow > 0 else 0.0

        gate_recon = GateStatus(
            name='reconciliation_error',
            passed=recon_error < 0.01,
            value=round(recon_error, 4),
            threshold=0.01,
        )
        gates.append(gate_recon)
        if not gate_recon.passed:
            failures.append(f'reconciliation_error={recon_error:.2%} >= 1%')

        # Gate 4: No active circuit breakers
        breaker = GlobalCircuitBreaker()
        circuit_triggered = breaker.is_triggered()

        gate_circuit = GateStatus(
            name='no_active_circuit_breakers',
            passed=not circuit_triggered,
            value=circuit_triggered,
            threshold=False,
        )
        gates.append(gate_circuit)
        if not gate_circuit.passed:
            reason = breaker.get_trigger_reason()
            failures.append(f'circuit_breaker_active: {reason}')

        return (len(failures) == 0, failures)

    def trigger_live(self, session: 'Session') -> bool:
        """
        Enable live trading at the current configured stage.

        Logs the transition to the audit log.
        """
        if not self._live_enabled:
            self._live_enabled = True
            log_event(
                session,
                'live_trading_enabled',
                f'stage={settings.shadow_stage}',
                'ok',
            )
            session.commit()
            return True
        return True  # Already live

    def rollback(self, session: 'Session') -> bool:
        """
        Revert to shadow mode and disable live trading.

        Logs the rollback to the audit log.
        """
        was_live = self._live_enabled
        self._live_enabled = False

        # Record stage transition
        stage_record = TradingStageRecord(
            stage=0,
            reason='rollback_to_shadow',
        )
        session.add(stage_record)

        log_event(
            session,
            'live_trading_rollback',
            f'previous_live={was_live}',
            'ok',
        )
        session.commit()
        return True

    def get_status(self, session: 'Session | None' = None) -> dict:
        """
        Get the current transition status.

        Returns a dict with mode, stage, gate statuses, and whether all gates pass.
        """
        can_live, reasons = self.can_go_live(session) if session else (False, ['no_session'])

        gate_statuses = []
        if session:
            # Rebuild gate statuses for reporting
            gates_data = []
            try:
                accuracy_data = self._accuracy_monitor.get_accuracy(window_days=30, session=session)
                gates_data.append({
                    'name': 'signal_accuracy',
                    'passed': accuracy_data['accuracy'] > 0.60,
                    'value': accuracy_data['accuracy'],
                    'threshold': 0.60,
                })
            except Exception:
                gates_data.append({
                    'name': 'signal_accuracy',
                    'passed': False,
                    'value': 0.0,
                    'threshold': 0.60,
                })

            cutoff = utcnow() - timedelta(days=30)
            stmt = select(ShadowResult).where(ShadowResult.resolved_at >= cutoff)
            resolved_count = len(list(session.scalars(stmt).all()))
            gates_data.append({
                'name': 'shadow_trades_count',
                'passed': resolved_count > 100,
                'value': resolved_count,
                'threshold': 100,
            })

            breaker = GlobalCircuitBreaker()
            gates_data.append({
                'name': 'no_active_circuit_breakers',
                'passed': not breaker.is_triggered(),
                'value': breaker.is_triggered(),
                'threshold': False,
            })

            gate_statuses = gates_data

        return {
            'mode': 'live' if self._live_enabled else 'shadow',
            'current_stage': settings.shadow_stage,
            'live_enabled': self._live_enabled,
            'gate_status': gate_statuses,
            'all_gates_passed': can_live,
            'blocking_reasons': reasons,
        }
