"""
Discrepancy detection between system DB, Polymarket API, and CTF contract positions.
"""

from dataclasses import dataclass
from enum import Enum

from polyclaw.reconciliation.types import PositionSummary


class DiscrepancyCategory(str, Enum):
    """Categories of discrepancies detected during reconciliation."""
    MISSING_ON_CHAIN = 'MISSING_ON_CHAIN'
    EXTRA_ON_CHAIN = 'EXTRA_ON_CHAIN'
    QUANTITY_MISMATCH = 'QUANTITY_MISMATCH'
    PRICE_MISMATCH = 'PRICE_MISMATCH'


@dataclass
class Discrepancy:
    """A single discrepancy between position sources."""
    category: DiscrepancyCategory
    market_id: str
    source1: str
    source2: str
    expected_value: float
    actual_value: float
    drift_usd: float


@dataclass
class DetectionResult:
    """Result of discrepancy detection across all position sources."""
    discrepancies: list[Discrepancy]
    total_drift_usd: float
    is_critical: bool  # True if total_drift_usd > 5.0


class DiscrepancyDetector:
    """
    Detects discrepancies between positions reported by the system DB,
    the Polymarket API, and the CTF blockchain contract.

    Comparison is done across all three sources pairwise. The `tolerance`
    parameter controls the floating-point comparison threshold (default $0.01).
    """

    CRITICAL_THRESHOLD: float = 5.0

    def __init__(self, tolerance: float = 0.01):
        """
        Initialize the detector.

        Args:
            tolerance: Dollar amount within which values are considered equal
                      for floating-point comparison. Default $0.01.
        """
        self.tolerance = tolerance

    def detect(
        self,
        system: dict[str, PositionSummary],
        api: dict[str, PositionSummary],
        chain: dict[str, PositionSummary],
    ) -> DetectionResult:
        """
        Compare positions across all three sources and return detected discrepancies.

        Args:
            system: Positions from the system database (market_id -> PositionSummary).
            api: Positions from the Polymarket API (market_id -> PositionSummary).
            chain: Positions from the CTF blockchain contract (market_id -> PositionSummary).

        Returns:
            A DetectionResult containing all discrepancies, total drift, and
            whether the situation is critical (total_drift_usd > 5.0).
        """
        discrepancies: list[Discrepancy] = []
        all_market_ids = set(system) | set(api) | set(chain)

        for market_id in all_market_ids:
            sys_pos = system.get(market_id)
            api_pos = api.get(market_id)
            chain_pos = chain.get(market_id)

            # Compare system vs API
            self._compare_pair(
                market_id, sys_pos, api_pos, 'SYSTEM_DB', 'POLYMARKET_API', discrepancies
            )
            # Compare system vs chain
            self._compare_pair(
                market_id, sys_pos, chain_pos, 'SYSTEM_DB', 'CTF_CONTRACT', discrepancies
            )
            # Compare API vs chain
            self._compare_pair(
                market_id, api_pos, chain_pos, 'POLYMARKET_API', 'CTF_CONTRACT', discrepancies
            )

        total_drift = sum(abs(d.drift_usd) for d in discrepancies)
        return DetectionResult(
            discrepancies=discrepancies,
            total_drift_usd=total_drift,
            is_critical=total_drift > self.CRITICAL_THRESHOLD,
        )

    def _compare_pair(
        self,
        market_id: str,
        pos1: PositionSummary | None,
        pos2: PositionSummary | None,
        source1_name: str,
        source2_name: str,
        discrepancies: list[Discrepancy],
    ) -> None:
        """
        Compare two position summaries and append any discrepancies.

        Handles four cases:
          1. Both missing — no discrepancy.
          2. First present, second missing — MISSING_ON_CHAIN / EXTRA_ON_CHAIN.
          3. First missing, second present — EXTRA_ON_CHAIN / MISSING_ON_CHAIN.
          4. Both present — QUANTITY_MISMATCH if quantities differ beyond tolerance.
        """
        if pos1 is None and pos2 is None:
            return

        if pos1 is not None and pos2 is None:
            # Case: present in source1, missing in source2
            if source2_name == 'CTF_CONTRACT':
                category = DiscrepancyCategory.MISSING_ON_CHAIN
            else:
                category = DiscrepancyCategory.EXTRA_ON_CHAIN
            discrepancies.append(Discrepancy(
                category=category,
                market_id=market_id,
                source1=source1_name,
                source2=source2_name,
                expected_value=pos1.notional_usd,
                actual_value=0.0,
                drift_usd=pos1.notional_usd,
            ))
            return

        if pos1 is None and pos2 is not None:
            # Case: missing in source1, present in source2
            if source1_name == 'CTF_CONTRACT':
                category = DiscrepancyCategory.MISSING_ON_CHAIN
            else:
                category = DiscrepancyCategory.EXTRA_ON_CHAIN
            discrepancies.append(Discrepancy(
                category=category,
                market_id=market_id,
                source1=source1_name,
                source2=source2_name,
                expected_value=0.0,
                actual_value=pos2.notional_usd,
                drift_usd=pos2.notional_usd,
            ))
            return

        # Both present — check for quantity mismatch
        assert pos1 is not None and pos2 is not None  # for type checker
        drift = abs(pos1.notional_usd - pos2.notional_usd)
        if drift > self.tolerance:
            discrepancies.append(Discrepancy(
                category=DiscrepancyCategory.QUANTITY_MISMATCH,
                market_id=market_id,
                source1=source1_name,
                source2=source2_name,
                expected_value=pos1.notional_usd,
                actual_value=pos2.notional_usd,
                drift_usd=drift,
            ))
