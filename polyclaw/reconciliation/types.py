"""
Shared types for the reconciliation package.

These dataclasses are used across detector.py, service.py, and alerts.py
and are kept in a separate module to avoid circular imports.
"""

from dataclasses import dataclass
from datetime import datetime


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
