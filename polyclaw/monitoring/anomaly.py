"""
Anomaly detection for PolyClaw — detects unusual PnL, volume, and spread patterns.

Anomalies are surfaced as AnomalyResult objects with severity levels and are
reported via the AlertRouter for CRITICAL anomalies.
"""

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polyclaw.models import AuditLog, Market, Order
from polyclaw.monitoring.alerts import Alert, AlertRouter, AlertSeverity
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


class AnomalySeverity(str, Enum):
    """Severity levels for anomaly detection results."""
    WARNING = 'WARNING'
    CRITICAL = 'CRITICAL'


@dataclass
class AnomalyResult:
    """Result of a single anomaly detection run."""
    detector_type: str  # e.g., 'pnl_spike', 'volume_anomaly', 'spread_anomaly'
    market_id: str | None  # None for system-wide anomalies (e.g., PnL spike)
    expected: float
    actual: float
    severity: AnomalySeverity
    reason: str = ''


class AnomalyDetector:
    """
    Detects anomalies in trading metrics using statistical thresholds.

    Uses a 30-day rolling window to establish baseline statistics and flags
    values that exceed mean +/- 3*std (PnL) or 3x the rolling average (volume/spread).

    On CRITICAL anomalies (pnl_spike), emits an alert via the NotificationService.
    """

    WINDOW_DAYS: int = 30
    ZSCORE_THRESHOLD: float = 3.0
    MULTIPLIER_THRESHOLD: float = 3.0

    def __init__(self, session: Session):
        """
        Initialize the anomaly detector.

        Args:
            session: SQLAlchemy database session.
        """
        self.session = session
        self._alert_router: AlertRouter | None = None

    @property
    def alert_router(self) -> AlertRouter:
        """Lazy-load the AlertRouter."""
        if self._alert_router is None:
            self._alert_router = AlertRouter()
        return self._alert_router

    # -------------------------------------------------------------------------
    # PnL spike detection
    # -------------------------------------------------------------------------

    def detect_pnl_spike(self) -> tuple[bool, str | None]:
        """
        Detect if today's PnL is anomalous compared to the 30-day rolling baseline.

        Uses daily aggregated PnL (from Order.notional_usd) over a 30-day window.
        Flags as anomalous if today's PnL falls outside mean +/- 3*std.

        Returns:
            A tuple of (is_anomaly, reason_or_none). If no historical data exists
            (fewer than 2 data points), returns (False, None).
        """
        today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=self.WINDOW_DAYS)

        # Fetch daily PnL aggregates for the rolling window
        rows = self.session.execute(
            select(
                func.date(Order.submitted_at).label('day'),
                func.sum(Order.notional_usd).label('daily_pnl'),
            )
            .where(Order.submitted_at >= window_start)
            .group_by(func.date(Order.submitted_at))
            .order_by(func.date(Order.submitted_at))
        ).all()

        if len(rows) < 2:
            logger.debug("detect_pnl_spike: fewer than 2 days of data, skipping")
            return False, None

        daily_pnls = [float(row.daily_pnl or 0) for row in rows]

        mean_pnl = statistics.mean(daily_pnls)
        std_pnl = statistics.stdev(daily_pnls) if len(daily_pnls) > 1 else 0.0

        # Today's PnL (most recent day in the result set)
        today_pnl = daily_pnls[-1] if daily_pnls else 0.0

        upper_bound = mean_pnl + self.ZSCORE_THRESHOLD * std_pnl
        lower_bound = mean_pnl - self.ZSCORE_THRESHOLD * std_pnl

        if std_pnl == 0:
            # All values identical — no spike possible
            return False, None

        if today_pnl > upper_bound or today_pnl < lower_bound:
            direction = 'up' if today_pnl > upper_bound else 'down'
            reason = (
                f"pnl_spike: today_pnl=${today_pnl:.2f} vs mean=${mean_pnl:.2f} "
                f"(std=${std_pnl:.2f}, bounds=[${lower_bound:.2f}, ${upper_bound:.2f}])"
            )
            logger.warning("Anomaly detected: %s", reason)

            # Emit CRITICAL alert for PnL spike
            self._emit_critical_alert('pnl_spike', reason)

            return True, reason

        return False, None

    # -------------------------------------------------------------------------
    # Volume anomaly detection
    # -------------------------------------------------------------------------

    def detect_volume_anomaly(self, market_id: str) -> tuple[bool, str | None]:
        """
        Detect if the latest 24h volume for a market is anomalous.

        Compares the current volume_24h_usd against the rolling 30-day average.
        Flags as anomalous if current volume > 3x the rolling average.

        Args:
            market_id: The market identifier.

        Returns:
            A tuple of (is_anomaly, reason_or_none). If no historical data,
            returns (False, None).
        """
        window_start = utcnow() - timedelta(days=self.WINDOW_DAYS)

        # Rolling average volume: average of volume_24h_usd over the window
        avg_result = self.session.scalar(
            select(func.avg(Market.volume_24h_usd))
            .where(Market.market_id == market_id)
            .where(Market.fetched_at >= window_start)
        )
        rolling_avg = float(avg_result) if avg_result is not None else 0.0

        # Current volume from the most recent market record
        current_row = self.session.scalar(
            select(Market.volume_24h_usd)
            .where(Market.market_id == market_id)
            .order_by(Market.fetched_at.desc())
            .limit(1)
        )
        current_volume = float(current_row) if current_row is not None else 0.0

        if rolling_avg <= 0 or current_volume <= 0:
            return False, None

        threshold = rolling_avg * self.MULTIPLIER_THRESHOLD
        if current_volume > threshold:
            reason = (
                f"volume_anomaly: market_id={market_id} "
                f"current_vol=${current_volume:.2f} > 3x_rolling_avg=${rolling_avg:.2f}"
            )
            logger.warning("Anomaly detected: %s", reason)
            return True, reason

        return False, None

    # -------------------------------------------------------------------------
    # Spread anomaly detection
    # -------------------------------------------------------------------------

    def detect_spread_anomaly(self, market_id: str) -> tuple[bool, str | None]:
        """
        Detect if the latest spread for a market is anomalous.

        Compares the current spread_bps against the rolling 30-day average spread.
        Flags as anomalous if current spread > 3x the rolling average.

        Args:
            market_id: The market identifier.

        Returns:
            A tuple of (is_anomaly, reason_or_none). If no historical data,
            returns (False, None).
        """
        window_start = utcnow() - timedelta(days=self.WINDOW_DAYS)

        # Rolling average spread: average of spread_bps over the window
        avg_result = self.session.scalar(
            select(func.avg(Market.spread_bps))
            .where(Market.market_id == market_id)
            .where(Market.fetched_at >= window_start)
        )
        rolling_avg = float(avg_result) if avg_result is not None else 0.0

        # Current spread from the most recent market record
        current_row = self.session.scalar(
            select(Market.spread_bps)
            .where(Market.market_id == market_id)
            .order_by(Market.fetched_at.desc())
            .limit(1)
        )
        current_spread = float(current_row) if current_row is not None else 0.0

        if rolling_avg <= 0 or current_spread <= 0:
            return False, None

        threshold = rolling_avg * self.MULTIPLIER_THRESHOLD
        if current_spread > threshold:
            reason = (
                f"spread_anomaly: market_id={market_id} "
                f"current_spread={current_spread:.0f}bps > 3x_rolling_avg={rolling_avg:.0f}bps"
            )
            logger.warning("Anomaly detected: %s", reason)
            return True, reason

        return False, None

    # -------------------------------------------------------------------------
    # Run all detectors
    # -------------------------------------------------------------------------

    def run_all(self) -> list[AnomalyResult]:
        """
        Run all anomaly detection methods and return consolidated results.

        Runs PnL spike detection (system-wide) and volume/spread anomaly
        detection for all active markets in the database.

        Returns:
            A list of AnomalyResult objects for all detected anomalies.
        """
        results: list[AnomalyResult] = []

        # 1. PnL spike detection
        is_anomaly, reason = self.detect_pnl_spike()
        if is_anomaly and reason:
            results.append(AnomalyResult(
                detector_type='pnl_spike',
                market_id=None,
                expected=0.0,  # Will be computed from rolling stats
                actual=0.0,
                severity=AnomalySeverity.CRITICAL,
                reason=reason,
            ))

        # 2. Volume anomaly for all active markets
        active_markets = self.session.scalars(
            select(Market.market_id)
            .where(Market.is_active == True)  # noqa: E712
            .distinct()
        ).all()

        for market_id in active_markets:
            is_anomaly, reason = self.detect_volume_anomaly(market_id)
            if is_anomaly and reason:
                avg_result = self.session.scalar(
                    select(func.avg(Market.volume_24h_usd))
                    .where(Market.market_id == market_id)
                )
                rolling_avg = float(avg_result) if avg_result else 0.0
                current_row = self.session.scalar(
                    select(Market.volume_24h_usd)
                    .where(Market.market_id == market_id)
                    .order_by(Market.fetched_at.desc())
                    .limit(1)
                )
                current = float(current_row) if current_row else 0.0
                results.append(AnomalyResult(
                    detector_type='volume_anomaly',
                    market_id=market_id,
                    expected=rolling_avg,
                    actual=current,
                    severity=AnomalySeverity.WARNING,
                    reason=reason,
                ))

            # 3. Spread anomaly for all active markets
            is_anomaly, reason = self.detect_spread_anomaly(market_id)
            if is_anomaly and reason:
                avg_result = self.session.scalar(
                    select(func.avg(Market.spread_bps))
                    .where(Market.market_id == market_id)
                )
                rolling_avg = float(avg_result) if avg_result else 0.0
                current_row = self.session.scalar(
                    select(Market.spread_bps)
                    .where(Market.market_id == market_id)
                    .order_by(Market.fetched_at.desc())
                    .limit(1)
                )
                current = float(current_row) if current_row else 0.0
                results.append(AnomalyResult(
                    detector_type='spread_anomaly',
                    market_id=market_id,
                    expected=rolling_avg,
                    actual=current,
                    severity=AnomalySeverity.WARNING,
                    reason=reason,
                ))

        return results

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _emit_critical_alert(self, detector_type: str, reason: str) -> None:
        """
        Emit a CRITICAL alert for a severe anomaly.

        Logs the event to the audit log and sends a notification via
        the NotificationService.

        Args:
            detector_type: The type of anomaly detector that triggered.
            reason: Human-readable description of the anomaly.
        """
        from polyclaw.safety import log_event

        log_event(
            self.session,
            f'anomaly_{detector_type}',
            reason,
            'critical',
        )
        self.session.commit()

        message = f"[CRITICAL ANOMALY] {detector_type}: {reason}"
        self.alert_router.send_critical(
            title=f"CRITICAL Anomaly: {detector_type}",
            message=message,
            detector_type=detector_type,
            reason=reason,
        )
        logger.error("CRITICAL anomaly alert emitted: %s", message)
