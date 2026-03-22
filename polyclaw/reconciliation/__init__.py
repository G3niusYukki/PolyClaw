"""
Reconciliation package for cross-source position drift detection.

This package reconciles positions across three sources:
  1. System DB  — positions stored in the local SQLite/Postgres database
  2. Polymarket API  — positions reported by the Polymarket API
  3. CTF Contract  — positions reported by the blockchain CTF contract

The ReconciliationService orchestrates fetching from all three sources,
detecting discrepancies, and triggering auto-close / alerts when drift is detected.
"""

from polyclaw.reconciliation.alerts import DriftAlerts
from polyclaw.reconciliation.detector import Discrepancy, DiscrepancyCategory, DiscrepancyDetector, DetectionResult
from polyclaw.reconciliation.service import ReconciliationService
from polyclaw.reconciliation.types import DiscrepancyItem, PositionSummary, ReconciliationReport

__all__ = [
    'ReconciliationService',
    'ReconciliationReport',
    'DiscrepancyItem',
    'PositionSummary',
    'DiscrepancyDetector',
    'DiscrepancyCategory',
    'DetectionResult',
    'Discrepancy',
    'DriftAlerts',
]
