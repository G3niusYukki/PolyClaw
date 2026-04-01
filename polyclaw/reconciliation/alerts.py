"""
Drift alert system — logs notifications for reconciliation discrepancies.
"""

import logging
from enum import Enum

from sqlalchemy.orm import Session

from polyclaw.reconciliation.types import DRIFT_CRITICAL_THRESHOLD, ReconciliationReport
from polyclaw.safety import log_event

logger = logging.getLogger(__name__)


class DriftSeverity(str, Enum):
    """Severity levels for drift alerts."""
    WARNING = 'WARNING'
    CRITICAL = 'CRITICAL'


class DriftAlerts:
    """
    Sends drift alerts for reconciliation discrepancies.

    Severity is determined by total drift:
      - WARNING: total_drift_usd < 5.0
      - CRITICAL: total_drift_usd >= 5.0

    Uses DRIFT_CRITICAL_THRESHOLD from reconciliation.types.
    """

    def __init__(self):
        pass

    def send_drift_alert(self, session: Session, report: ReconciliationReport) -> DriftSeverity:
        """
        Send a drift alert based on the reconciliation report.

        Args:
            session: The database session for audit logging.
            report: The reconciliation report containing drift details.

        Returns:
            The severity level of the alert that was sent.
        """
        if report.total_drift_usd >= DRIFT_CRITICAL_THRESHOLD:
            severity = DriftSeverity.CRITICAL
        else:
            severity = DriftSeverity.WARNING

        # Build alert message
        discrepancy_details = [
            f"market={d.market_id} [{d.category or 'N/A'}] drift=${d.drift_usd:.4f}"
            for d in report.discrepancy_items
        ]
        message = (
            f"RECONCILIATION DRIFT [{severity.value}] "
            f"total_drift_usd={report.total_drift_usd:.4f} "
            f"discrepancies={len(report.discrepancy_items)} "
            f"items={discrepancy_details}"
        )

        # Always log to audit log
        log_event(
            session,
            'reconciliation_drift',
            message,
            severity.value.lower(),
        )

        # Send notification for CRITICAL alerts only
        if severity == DriftSeverity.CRITICAL:
            logger.critical("RECONCILIATION DRIFT ALERT: %s", message)

        return severity
