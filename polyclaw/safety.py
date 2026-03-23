from __future__ import annotations

import logging
import time as _time_module
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polyclaw.models import AuditLog, Decision, Order
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit Breaker state helpers (stored in memory for runtime state)
# ---------------------------------------------------------------------------

class _CircuitState:
    """In-memory circuit breaker state shared by all instances."""

    def __init__(self):
        self._global_triggered: bool = False
        self._global_reason: str = ''
        self._global_triggered_at: datetime | None = None
        self._strategy_states: dict[str, dict] = {}

    def is_global_triggered(self) -> bool:
        return self._global_triggered

    def get_global_reason(self) -> str:
        return self._global_reason

    def get_global_triggered_at(self) -> datetime | None:
        return self._global_triggered_at

    def trigger_global(self, reason: str) -> None:
        self._global_triggered = True
        self._global_reason = reason
        self._global_triggered_at = utcnow()

    def reset_global(self) -> None:
        self._global_triggered = False
        self._global_reason = ''
        self._global_triggered_at = None

    def is_strategy_triggered(self, strategy_id: str) -> bool:
        return bool(self._strategy_states.get(strategy_id, {}).get('triggered', False))

    def get_strategy_reason(self, strategy_id: str) -> str:
        return str(self._strategy_states.get(strategy_id, {}).get('reason', ''))

    def get_strategy_triggered_at(self, strategy_id: str) -> datetime | None:
        return self._strategy_states.get(strategy_id, {}).get('triggered_at', None)

    def trigger_strategy(self, strategy_id: str, reason: str) -> None:
        if strategy_id not in self._strategy_states:
            self._strategy_states[strategy_id] = {}
        self._strategy_states[strategy_id]['triggered'] = True
        self._strategy_states[strategy_id]['reason'] = reason
        self._strategy_states[strategy_id]['triggered_at'] = utcnow()

    def reset_strategy(self, strategy_id: str) -> None:
        if strategy_id in self._strategy_states:
            self._strategy_states[strategy_id]['triggered'] = False
            self._strategy_states[strategy_id]['reason'] = ''
            self._strategy_states[strategy_id]['triggered_at'] = None
            self._strategy_states[strategy_id]['manual_review_required'] = True

    def is_strategy_awaiting_manual_review(self, strategy_id: str) -> bool:
        return bool(self._strategy_states.get(strategy_id, {}).get('manual_review_required', False))

    def clear_strategy_manual_review(self, strategy_id: str) -> None:
        if strategy_id in self._strategy_states:
            self._strategy_states[strategy_id]['manual_review_required'] = False
            # Auto-reset also clears the triggered flag so trading can resume
            self._strategy_states[strategy_id]['triggered'] = False


# Shared global state instance
_circuit_state = _CircuitState()


# ---------------------------------------------------------------------------
# Circuit Breakers
# ---------------------------------------------------------------------------

class GlobalCircuitBreaker:
    """
    Global circuit breaker that halts all trading when critical thresholds are breached.

    Triggers:
      - Portfolio drawdown > 20%
      - Daily loss > $500
      - Data stale > 15 minutes
      - Execution failure rate > 20%

    Auto-reset: only manual reset is supported (critical trigger).
    """

    def __init__(
        self,
        max_drawdown_pct: float = 20.0,
        max_daily_loss_usd: float = 500.0,
        max_data_latency_minutes: int = 15,
        max_exec_failure_rate: float = 0.20,
    ):
        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_data_latency_minutes = max_data_latency_minutes
        self.max_exec_failure_rate = max_exec_failure_rate

    def check(
        self,
        session: Session,
        portfolio_value: float,
        portfolio_drawdown_pct: float,
        latest_data_fetched_at: datetime | None,
        recent_orders: list[Order] | None = None,
    ) -> bool:
        """
        Run all global circuit breaker checks.

        Returns True if a trigger condition is met (circuit is blown).
        Returns False if all checks pass.
        """
        from polyclaw.timeutils import utcnow

        # 1. Portfolio drawdown check
        if portfolio_drawdown_pct > self.max_drawdown_pct:
            reason = (
                f"portfolio_drawdown_exceeded: {portfolio_drawdown_pct:.1f}% > "
                f"{self.max_drawdown_pct}% (max allowed)"
            )
            self.trigger(reason, session)
            return True

        # 2. Daily loss check
        daily_loss = self._calculate_daily_loss(session)
        if daily_loss < 0 and abs(daily_loss) > self.max_daily_loss_usd:
            reason = (
                f"daily_loss_exceeded: ${abs(daily_loss):.2f} > "
                f"${self.max_daily_loss_usd:.2f} limit"
            )
            self.trigger(reason, session)
            return True

        # 3. Data staleness check
        if latest_data_fetched_at is not None:
            age_minutes = (utcnow() - latest_data_fetched_at).total_seconds() / 60.0
            if age_minutes > self.max_data_latency_minutes:
                reason = (
                    f"data_stale: {age_minutes:.1f}min > "
                    f"{self.max_data_latency_minutes}min threshold"
                )
                self.trigger(reason, session)
                return True

        # 4. Execution failure rate check
        if recent_orders is not None and len(recent_orders) > 0:
            failed = sum(1 for o in recent_orders if o.status in ('failed', 'error', 'rejected'))
            failure_rate = failed / len(recent_orders)
            if failure_rate > self.max_exec_failure_rate:
                reason = (
                    f"exec_failure_rate_exceeded: {failure_rate:.1%} > "
                    f"{self.max_exec_failure_rate:.1%} "
                    f"(failed={failed}/{len(recent_orders)})"
                )
                self.trigger(reason, session)
                return True

        return False

    def trigger(self, reason: str, session: Session | None = None) -> None:
        """Manually trigger the global circuit breaker."""
        _circuit_state.trigger_global(reason)
        if session is not None:
            log_event(session, 'global_circuit_breaker', reason, 'triggered')
            session.commit()

    def is_triggered(self) -> bool:
        """Check if the global circuit breaker is currently triggered."""
        return _circuit_state.is_global_triggered()

    def get_trigger_reason(self) -> str:
        """Get the reason the global circuit breaker was triggered."""
        return _circuit_state.get_global_reason()

    def get_triggered_at(self) -> datetime | None:
        """Get when the global circuit breaker was triggered."""
        return _circuit_state.get_global_triggered_at()

    def reset(self) -> None:
        """
        Reset the global circuit breaker.
        This is a manual reset operation only.
        """
        _circuit_state.reset_global()

    def _calculate_daily_loss(self, session: Session) -> float:
        """Calculate the daily PnL from executed orders."""
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = session.scalars(
            select(func.coalesce(func.sum(Order.notional_usd), 0.0)).where(
                Order.submitted_at >= start
            )
        ).all()
        total_expended = float(sum(rows) or 0.0)
        # Positive notional means we spent money, approximate daily PnL
        # (this is a proxy; true PnL requires realized P&L tracking)
        return -total_expended


class StrategyCircuitBreaker:
    """
    Per-strategy circuit breaker that halts a specific strategy when thresholds are breached.

    Triggers:
      - Strategy drawdown > 10%
      - Execution failure rate > 20%

    Auto-reset: after 24h (configurable) + manual review required.
    """

    def __init__(
        self,
        strategy_id: str,
        max_drawdown_pct: float = 10.0,
        max_exec_failure_rate: float = 0.20,
        auto_reset_after_hours: int = 24,
    ):
        self.strategy_id = strategy_id
        self.max_drawdown_pct = max_drawdown_pct
        self.max_exec_failure_rate = max_exec_failure_rate
        self.auto_reset_after_hours = auto_reset_after_hours

    def check(
        self,
        session: Session,
        strategy_drawdown_pct: float,
        recent_orders: list[Order] | None = None,
    ) -> bool:
        """
        Run strategy-level circuit breaker checks.

        Returns True if a trigger condition is met.
        """
        # Check if auto-reset window has passed
        triggered_at = _circuit_state.get_strategy_triggered_at(self.strategy_id)
        if triggered_at is not None:
            elapsed = (utcnow() - triggered_at).total_seconds() / 3600.0
            if elapsed >= self.auto_reset_after_hours:
                # Auto-reset eligible but still requires manual review
                _circuit_state.clear_strategy_manual_review(self.strategy_id)

        # Already triggered and awaiting review
        if _circuit_state.is_strategy_triggered(self.strategy_id):
            if not _circuit_state.is_strategy_awaiting_manual_review(self.strategy_id):
                return True

        # 1. Strategy drawdown check
        if strategy_drawdown_pct > self.max_drawdown_pct:
            reason = (
                f"strategy_drawdown_exceeded: {strategy_drawdown_pct:.1f}% > "
                f"{self.max_drawdown_pct}% for strategy={self.strategy_id}"
            )
            self.trigger(reason, session)
            return True

        # 2. Execution failure rate check
        if recent_orders is not None and len(recent_orders) > 0:
            failed = sum(1 for o in recent_orders if o.status in ('failed', 'error', 'rejected'))
            failure_rate = failed / len(recent_orders)
            if failure_rate > self.max_exec_failure_rate:
                reason = (
                    f"strategy_exec_failure_rate_exceeded: {failure_rate:.1%} > "
                    f"{self.max_exec_failure_rate:.1%} for strategy={self.strategy_id}"
                )
                self.trigger(reason, session)
                return True

        return False

    def trigger(self, reason: str, session: Session | None = None) -> None:
        """Trigger the strategy circuit breaker."""
        _circuit_state.trigger_strategy(self.strategy_id, reason)
        if session is not None:
            log_event(
                session,
                'strategy_circuit_breaker',
                f"strategy={self.strategy_id}|{reason}",
                'triggered',
            )
            session.commit()

    def is_triggered(self) -> bool:
        """Check if this strategy's circuit breaker is triggered."""
        return _circuit_state.is_strategy_triggered(self.strategy_id)

    def is_awaiting_manual_review(self) -> bool:
        """Check if this strategy is awaiting manual review after auto-reset."""
        return _circuit_state.is_strategy_awaiting_manual_review(self.strategy_id)

    def get_trigger_reason(self) -> str:
        """Get the reason the circuit breaker was triggered."""
        return _circuit_state.get_strategy_reason(self.strategy_id)

    def get_triggered_at(self) -> datetime | None:
        """Get when the circuit breaker was triggered."""
        return _circuit_state.get_strategy_triggered_at(self.strategy_id)

    def reset(self) -> None:
        """Manually reset the strategy circuit breaker."""
        _circuit_state.reset_strategy(self.strategy_id)

    def check_and_allow(self, session: Session) -> bool:
        """
        Convenience method: return True if trade is allowed, False if blocked.
        A strategy is blocked whenever its circuit breaker is triggered,
        regardless of whether manual review is pending.
        """
        if self.is_triggered():
            return False
        return True


# ---------------------------------------------------------------------------
# CTF Live Circuit Breaker
# ---------------------------------------------------------------------------


class CTFLiveCircuitBreaker:
    """Circuit breaker for CTF live trading failures.

    Triggers kill switch on:
    - 3 consecutive eth_sendTransaction failures
    - Signing exception
    - 5 RPC errors in 10 minutes (sliding window)
    """

    def __init__(
        self,
        max_consecutive_send_failures: int = 3,
        max_rpc_errors: int = 5,
        error_window_seconds: int = 600,
    ):
        self.max_consecutive_send_failures = max_consecutive_send_failures
        self.max_rpc_errors = max_rpc_errors
        self.error_window_seconds = error_window_seconds
        self._send_failures: int = 0
        self._rpc_errors: list[float] = []

    def record_send_failure(self) -> None:
        self._send_failures += 1
        if self._send_failures >= self.max_consecutive_send_failures:
            self._trigger_kill_switch(
                f"ctf_send_failure: {self._send_failures} consecutive failures"
            )

    def record_send_success(self) -> None:
        self._send_failures = 0

    def record_rpc_error(self) -> None:
        now = _time_module.monotonic()
        self._rpc_errors.append(now)
        cutoff = now - self.error_window_seconds
        self._rpc_errors = [t for t in self._rpc_errors if t > cutoff]
        if len(self._rpc_errors) >= self.max_rpc_errors:
            self._trigger_kill_switch(
                f"ctf_rpc_errors: {len(self._rpc_errors)} in {self.error_window_seconds}s"
            )

    def check_and_allow(self, session: Session | None) -> bool:
        if _circuit_state.is_global_triggered():
            return False
        return True

    def _trigger_kill_switch(self, reason: str) -> None:
        _circuit_state.trigger_global(f"CTF_LIVE:{reason}")
        logger.critical("CTF live circuit breaker triggered: %s", reason)


# Singleton
_ctf_circuit_breaker: CTFLiveCircuitBreaker | None = None


def get_ctf_circuit_breaker() -> CTFLiveCircuitBreaker:
    global _ctf_circuit_breaker
    if _ctf_circuit_breaker is None:
        _ctf_circuit_breaker = CTFLiveCircuitBreaker()
    return _ctf_circuit_breaker


def reset_ctf_circuit_breaker() -> None:
    """Reset the CTF circuit breaker singleton and global circuit state.

    Exists primarily for use in test fixtures to ensure a clean state between tests.
    """
    global _ctf_circuit_breaker
    _ctf_circuit_breaker = None
    _circuit_state.reset_global()


# ---------------------------------------------------------------------------
# Existing helpers
# ---------------------------------------------------------------------------

def log_event(session: Session, action: str, payload: str, result: str = "ok") -> AuditLog:
    row = AuditLog(action=action, payload=payload, result=result)
    session.add(row)
    session.flush()
    return row


def kill_switch_state(session: Session) -> dict:
    row = session.scalar(select(AuditLog).where(AuditLog.action == 'kill_switch').order_by(AuditLog.created_at.desc()))
    if not row:
        return {'enabled': False, 'reason': ''}
    enabled = row.result == 'enabled'
    return {'enabled': enabled, 'reason': row.payload}


def set_kill_switch(session: Session, enabled: bool, reason: str = '') -> dict:
    log_event(session, 'kill_switch', reason, 'enabled' if enabled else 'disabled')
    session.commit()
    return {'enabled': enabled, 'reason': reason}


def daily_executed_notional(session: Session) -> float:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(select(func.coalesce(func.sum(Order.notional_usd), 0.0)).where(Order.submitted_at >= start))
    return float(total or 0.0)


def open_proposed_count(session: Session) -> int:
    total = session.scalar(select(func.count(Decision.id)).where(Decision.status == 'proposed'))
    return int(total or 0)
