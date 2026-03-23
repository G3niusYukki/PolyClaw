"""
Shared types and constants for the reconciliation package.

These dataclasses are used across detector.py, service.py, and alerts.py
and are kept in a separate module to avoid circular imports.
"""

from dataclasses import dataclass
from datetime import datetime

# Threshold constants — must stay consistent across reconciliation/.
# - DRIFT_CRITICAL_THRESHOLD (5.0): triggers CRITICAL severity in alerts.py and
#   is_critical=True in detector.py.
# - DRIFT_AUTO_CLOSE_THRESHOLD (10.0): triggers auto-close in service.py.
DRIFT_CRITICAL_THRESHOLD: float = 5.0
DRIFT_AUTO_CLOSE_THRESHOLD: float = 10.0


@dataclass
class PositionSummary:
    """Normalized position data from any source."""
    market_id: str
    side: str
    quantity: float
    notional_usd: float
    avg_price: float
    source: str = ''


@dataclass
class DiscrepancyItem:
    """A single discrepancy item in a reconciliation report."""
    market_id: str
    source1: str
    source2: str
    expected_value: float
    actual_value: float
    drift_usd: float
    category: str = ''


@dataclass
class ReconciliationReport:
    """Report produced after a full reconciliation run."""
    drift_detected: bool
    total_drift_usd: float
    discrepancy_items: list[DiscrepancyItem]
    timestamp: datetime
    auto_close_triggered: bool = False
    auto_close_count: int = 0
