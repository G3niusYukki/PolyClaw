"""
Reconciliation service — reconciles positions across system DB, Polymarket API, and CTF contract.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.models import Order, Position
from polyclaw.reconciliation.alerts import DriftAlerts
from polyclaw.reconciliation.detector import DetectionResult, DiscrepancyDetector
from polyclaw.reconciliation.types import DiscrepancyItem, PositionSummary, ReconciliationReport
from polyclaw.safety import log_event
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from polyclaw.providers.ctf import PolymarketCTFProvider
    from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider


class ReconciliationService:
    """
    Reconciles positions across three sources:
      1. System DB  — positions stored in the local database
      2. Polymarket API  — positions reported by the Polymarket REST API
      3. CTF Contract  — positions reported by the blockchain CTF contract

    After reconciliation, if total drift exceeds `auto_close_threshold`, the service
    submits offsetting orders to close the drifting positions and sends alerts.

    Usage:
        service = ReconciliationService(session, ctf_provider, polymarket_api)
        report = service.reconcile()
    """

    # Threshold in USD above which auto-close is triggered
    DEFAULT_AUTO_CLOSE_THRESHOLD: float = 10.0

    def __init__(
        self,
        session: Session,
        ctf_provider: 'PolymarketCTFProvider',
        polymarket_api: 'PolymarketGammaProvider',
        auto_close_threshold: float | None = None,
    ):
        """
        Initialize the reconciliation service.

        Args:
            session: SQLAlchemy database session.
            ctf_provider: Provider for CTF contract position data.
            polymarket_api: Provider for Polymarket REST API data.
            auto_close_threshold: USD threshold for triggering auto-close.
                                  Defaults to 10.0.
        """
        self.session = session
        self.ctf_provider = ctf_provider
        self.polymarket_api = polymarket_api
        self.auto_close_threshold = auto_close_threshold or self.DEFAULT_AUTO_CLOSE_THRESHOLD
        self.detector = DiscrepancyDetector(tolerance=0.01)
        self.drift_alerts = DriftAlerts()
        self._last_report: ReconciliationReport | None = None

    def reconcile(self) -> ReconciliationReport:
        """
        Perform a full reconciliation across system DB, Polymarket API, and CTF contract.

        Steps:
          1. Fetch positions from all three sources.
          2. Run discrepancy detection.
          3. If drift is detected, send alerts.
          4. If total drift exceeds auto_close_threshold, submit offsetting orders.
          5. Log all actions to the audit log.

        Returns:
            A ReconciliationReport summarizing the results.
        """
        log_event(self.session, 'reconciliation_start', 'reconciliation cycle started', 'ok')

        # Step 1: Gather positions from all three sources
        system_positions = self.get_system_positions(self.session)
        api_positions = self.get_api_positions()
        chain_positions = self.get_chain_positions()

        log_event(
            self.session,
            'reconciliation_positions_fetched',
            f"system={len(system_positions)} api={len(api_positions)} chain={len(chain_positions)}",
            'ok',
        )

        # Step 2: Detect discrepancies
        detection_result = self.detector.detect(system_positions, api_positions, chain_positions)

        # Convert Discrepancy to DiscrepancyItem for the report
        discrepancy_items = [
            DiscrepancyItem(
                market_id=d.market_id,
                source1=d.source1,
                source2=d.source2,
                expected_value=d.expected_value,
                actual_value=d.actual_value,
                drift_usd=d.drift_usd,
                category=d.category.value,
            )
            for d in detection_result.discrepancies
        ]

        report = ReconciliationReport(
            drift_detected=detection_result.is_critical or len(discrepancy_items) > 0,
            total_drift_usd=detection_result.total_drift_usd,
            discrepancy_items=discrepancy_items,
            timestamp=utcnow(),
            auto_close_triggered=False,
            auto_close_count=0,
        )

        # Step 3: Send alerts
        if report.drift_detected:
            severity = self.drift_alerts.send_drift_alert(self.session, report)
            log_event(
                self.session,
                'reconciliation_alert_sent',
                f"severity={severity.value} total_drift=${report.total_drift_usd:.4f}",
                'ok',
            )

        # Step 4: Auto-close if threshold exceeded
        if self.should_auto_close(report.total_drift_usd):
            auto_close_count = self._auto_close(report, system_positions)
            report = ReconciliationReport(
                drift_detected=report.drift_detected,
                total_drift_usd=report.total_drift_usd,
                discrepancy_items=report.discrepancy_items,
                timestamp=report.timestamp,
                auto_close_triggered=True,
                auto_close_count=auto_close_count,
            )

        self._last_report = report
        self.session.commit()

        log_event(
            self.session,
            'reconciliation_complete',
            f"drift_detected={report.drift_detected} total_drift=${report.total_drift_usd:.4f} "
            f"auto_close={report.auto_close_triggered} count={report.auto_close_count}",
            'ok',
        )

        return report

    def get_system_positions(self, session: Session) -> dict[str, PositionSummary]:
        """
        Fetch current open positions from the system database.

        Args:
            session: SQLAlchemy database session.

        Returns:
            A dict mapping market_id -> PositionSummary.
        """
        rows = session.scalars(
            select(Position).where(Position.is_open == True)  # noqa: E712
        ).all()
        return {
            row.market_id: PositionSummary(
                market_id=row.market_id,
                side=row.side,
                quantity=row.quantity,
                notional_usd=row.notional_usd,
                avg_price=row.avg_price,
                source='SYSTEM_DB',
            )
            for row in rows
        }

    def get_api_positions(self) -> dict[str, PositionSummary]:
        """
        Fetch positions from the Polymarket REST API.

        Currently mocked — calls the CTF provider's get_positions() for now.

        Returns:
            A dict mapping market_id -> PositionSummary.
        """
        import asyncio
        try:
            positions = self.ctf_provider.get_positions()
            if asyncio.iscoroutine(positions):
                positions = asyncio.run(positions)
        except RuntimeError:
            positions = self.ctf_provider.get_positions()
            if asyncio.iscoroutine(positions):
                positions = asyncio.run(positions)

        # positions is a list[dict] from the CTF provider
        result: dict[str, PositionSummary] = {}
        for pos_dict in positions:
            market_id = pos_dict.get('market_id', '')
            if market_id:
                result[market_id] = PositionSummary(
                    market_id=market_id,
                    side=pos_dict.get('side', 'yes'),
                    quantity=pos_dict.get('quantity', 0.0),
                    notional_usd=pos_dict.get('notional_usd', 0.0),
                    avg_price=pos_dict.get('avg_price', 0.0),
                    source='POLYMARKET_API',
                )
        return result

    def get_chain_positions(self) -> dict[str, PositionSummary]:
        """
        Fetch positions from the CTF blockchain contract.

        Currently mocked — calls the CTF provider's get_positions() for now.

        Returns:
            A dict mapping market_id -> PositionSummary.
        """
        import asyncio
        try:
            positions = self.ctf_provider.get_positions()
            if asyncio.iscoroutine(positions):
                positions = asyncio.run(positions)
        except RuntimeError:
            positions = self.ctf_provider.get_positions()
            if asyncio.iscoroutine(positions):
                positions = asyncio.run(positions)

        # positions is a list[dict] from the CTF provider
        result: dict[str, PositionSummary] = {}
        for pos_dict in positions:
            market_id = pos_dict.get('market_id', '')
            if market_id:
                result[market_id] = PositionSummary(
                    market_id=market_id,
                    side=pos_dict.get('side', 'yes'),
                    quantity=pos_dict.get('quantity', 0.0),
                    notional_usd=pos_dict.get('notional_usd', 0.0),
                    avg_price=pos_dict.get('avg_price', 0.0),
                    source='CTF_CONTRACT',
                )
        return result

    def should_auto_close(self, total_drift_usd: float) -> bool:
        """
        Check whether auto-close should be triggered based on total drift.

        Args:
            total_drift_usd: The total drift in USD from the reconciliation report.

        Returns:
            True if total drift exceeds the auto-close threshold.
        """
        return total_drift_usd > self.auto_close_threshold

    def _auto_close(
        self,
        report: ReconciliationReport,
        system_positions: dict[str, PositionSummary],
    ) -> int:
        """
        Submit offsetting orders to close positions affected by drift.

        For each market with drift, submits a closing order of equal size
        on the opposite side.

        Args:
            report: The reconciliation report containing discrepancies.
            system_positions: The system positions to close.

        Returns:
            The number of auto-close orders submitted.
        """
        closed_count = 0
        for item in report.discrepancy_items:
            system_pos = system_positions.get(item.market_id)
            if system_pos is None:
                continue

            # Determine offsetting side
            offset_side = 'no' if system_pos.side == 'yes' else 'yes'

            try:
                self._submit_close_order(system_pos, offset_side)
                log_event(
                    self.session,
                    'auto_close_order_submitted',
                    f"market={item.market_id} side={offset_side} "
                    f"quantity={system_pos.quantity} drift=${item.drift_usd:.4f}",
                    'ok',
                )
                closed_count += 1
            except Exception as exc:
                log_event(
                    self.session,
                    'auto_close_order_failed',
                    f"market={item.market_id} error={exc}",
                    'error',
                )

        if closed_count > 0:
            log_event(
                self.session,
                'auto_close_batch_complete',
                f"closed={closed_count} total_drift=${report.total_drift_usd:.4f}",
                'ok',
            )

        return closed_count

    def _submit_close_order(self, position: PositionSummary, side: str) -> None:
        """
        Submit an offsetting close order for a position.

        In paper mode, this records the close in the database.
        In live mode, this would submit to the execution provider.

        Args:
            position: The position to close.
            side: The offsetting side ('yes' or 'no').
        """
        from polyclaw.timeutils import utcnow

        # Update the position record to mark it closed
        db_pos = self.session.scalar(
            select(Position).where(Position.market_id == position.market_id, Position.is_open == True)  # noqa: E712
        )
        if db_pos:
            db_pos.is_open = False

        # Record the close order
        close_order = Order(
            decision_id_fk=0,  # Auto-close has no associated decision
            client_order_id=f'auto-close-{position.market_id}-{utcnow().timestamp()}',
            mode='paper',
            side=side,
            price=position.avg_price,
            size=position.quantity,
            notional_usd=position.notional_usd,
            status='submitted',
        )
        self.session.add(close_order)
        self.session.flush()

    @property
    def last_report(self) -> ReconciliationReport | None:
        """Return the last reconciliation report, if available."""
        return self._last_report
