"""
Tests for the reconciliation package.
"""

from unittest.mock import MagicMock, patch

import pytest

from polyclaw.reconciliation.alerts import DriftAlerts, DriftSeverity
from polyclaw.reconciliation.detector import (
    DiscrepancyCategory,
    DiscrepancyDetector,
)
from polyclaw.reconciliation.service import ReconciliationService
from polyclaw.reconciliation.types import DiscrepancyItem, PositionSummary, ReconciliationReport
from polyclaw.timeutils import utcnow

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def make_summary(
    market_id: str,
    side: str = 'yes',
    quantity: float = 1.0,
    notional_usd: float = 10.0,
    avg_price: float = 0.5,
    source: str = '',
) -> PositionSummary:
    return PositionSummary(
        market_id=market_id,
        side=side,
        quantity=quantity,
        notional_usd=notional_usd,
        avg_price=avg_price,
        source=source,
    )


# ---------------------------------------------------------------------------
# DiscrepancyDetector tests
# ---------------------------------------------------------------------------

class TestDiscrepancyDetector:
    def test_matching_positions_no_discrepancies(self):
        """When all three sources report identical positions, no discrepancies should be found."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        chain = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}

        result = detector.detect(system, api, chain)

        assert result.discrepancies == []
        assert result.total_drift_usd == 0.0
        assert result.is_critical is False

    def test_missing_on_chain(self):
        """System has position but chain is missing -> MISSING_ON_CHAIN discrepancy."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=5.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=5.0)}
        chain = {}  # missing on chain

        result = detector.detect(system, api, chain)

        mismatches = [d for d in result.discrepancies if d.category == DiscrepancyCategory.MISSING_ON_CHAIN]
        assert len(mismatches) >= 1
        assert any(d.market_id == 'mkt-1' for d in mismatches)

    def test_extra_on_chain(self):
        """Chain has position but system is missing -> EXTRA_ON_CHAIN discrepancy."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {}
        api = {}
        chain = {'mkt-1': make_summary('mkt-1', notional_usd=5.0)}

        result = detector.detect(system, api, chain)

        extras = [d for d in result.discrepancies if d.category == DiscrepancyCategory.EXTRA_ON_CHAIN]
        assert len(extras) >= 1

    def test_quantity_mismatch(self):
        """Same market on two sources but different notional_usd -> QUANTITY_MISMATCH."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=7.0)}  # differs by 3.0
        chain = {}

        result = detector.detect(system, api, chain)

        mismatches = [d for d in result.discrepancies if d.category == DiscrepancyCategory.QUANTITY_MISMATCH]
        assert len(mismatches) >= 1
        drift_sum = sum(d.drift_usd for d in mismatches)
        assert drift_sum > 0

    def test_tolerance_ignores_small_differences(self):
        """Differences within tolerance should not be flagged as discrepancies."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=10.005)}  # within 0.01 tolerance
        chain = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}

        result = detector.detect(system, api, chain)

        mismatches = [d for d in result.discrepancies if d.category == DiscrepancyCategory.QUANTITY_MISMATCH]
        assert mismatches == []

    def test_is_critical_when_total_drift_above_5(self):
        """is_critical should be True when total_drift_usd > 5.0."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=2.0)}  # drift of 8.0
        chain = {}

        result = detector.detect(system, api, chain)

        assert result.total_drift_usd > 5.0
        assert result.is_critical is True

    def test_is_not_critical_when_total_drift_below_5(self):
        """is_critical should be False when total_drift_usd <= 5.0."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}
        api = {'mkt-1': make_summary('mkt-1', notional_usd=10.0)}  # same as system
        chain = {'mkt-1': make_summary('mkt-1', notional_usd=8.0)}  # drift of 2.0 vs system/api

        result = detector.detect(system, api, chain)

        # system vs api: 0 drift; system vs chain: 2.0; api vs chain: 2.0; total = 4.0
        assert result.total_drift_usd <= 5.0
        assert result.is_critical is False

    def test_multiple_markets_all_have_drift(self):
        """Multiple markets with drift should sum up correctly."""
        detector = DiscrepancyDetector(tolerance=0.01)

        system = {
            'mkt-1': make_summary('mkt-1', notional_usd=10.0),
            'mkt-2': make_summary('mkt-2', notional_usd=5.0),
        }
        api = {
            'mkt-1': make_summary('mkt-1', notional_usd=8.0),  # drift 2.0
            'mkt-2': make_summary('mkt-2', notional_usd=3.0),  # drift 2.0
        }
        chain = {}  # missing on chain for both

        result = detector.detect(system, api, chain)

        assert result.total_drift_usd > 0
        # All three comparisons per market should produce discrepancies
        assert len(result.discrepancies) > 0

    def test_empty_positions_all_sources(self):
        """All sources empty should produce no discrepancies."""
        detector = DiscrepancyDetector(tolerance=0.01)
        result = detector.detect({}, {}, {})
        assert result.discrepancies == []
        assert result.total_drift_usd == 0.0
        assert result.is_critical is False


# ---------------------------------------------------------------------------
# ReconciliationService tests
# ---------------------------------------------------------------------------

class TestReconciliationService:
    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    @pytest.fixture
    def mock_ctf_provider(self):
        provider = MagicMock()
        provider.get_positions.return_value = {}
        return provider

    @pytest.fixture
    def mock_polymarket_api(self):
        return MagicMock()

    def test_reconcile_with_no_positions_no_drift(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        """Reconcile with no positions anywhere should produce no drift."""
        service = ReconciliationService(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
        )

        # Mock get_system_positions to return empty
        with patch.object(service, 'get_system_positions', return_value={}):
            report = service.reconcile()

        assert report.drift_detected is False
        assert report.total_drift_usd == 0.0
        assert report.discrepancy_items == []

    def test_should_auto_close_above_threshold(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        """should_auto_close returns True when drift exceeds threshold."""
        service = ReconciliationService(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
            auto_close_threshold=10.0,
        )
        assert service.should_auto_close(15.0) is True
        assert service.should_auto_close(10.0) is False  # exactly at threshold
        assert service.should_auto_close(9.99) is False

    def test_should_auto_close_custom_threshold(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        """Custom auto_close_threshold is respected."""
        service = ReconciliationService(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
            auto_close_threshold=3.0,
        )
        assert service.should_auto_close(5.0) is True
        assert service.should_auto_close(2.0) is False

    def test_reconcile_sets_last_report(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        """reconcile() should store the report so last_report property works."""
        service = ReconciliationService(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
        )
        assert service.last_report is None

        with patch.object(service, 'get_system_positions', return_value={}):
            report = service.reconcile()

        assert service.last_report is report
        assert service.last_report is not None

    def test_reconcile_auto_close_threshold(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        """Auto-close should be triggered when drift exceeds threshold."""
        service = ReconciliationService(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
            auto_close_threshold=10.0,
        )

        # Set up CTF provider to return positions as list[dict]
        mock_ctf_provider.get_positions.return_value = [
            {'market_id': 'mkt-1', 'side': 'yes', 'quantity': 1.0, 'notional_usd': 5.0, 'avg_price': 0.5},
        ]

        # Mock the system DB to have a position that differs (drift will be detected)
        system_positions = {
            'mkt-1': make_summary('mkt-1', notional_usd=20.0),  # drift of 15.0 vs chain
        }

        with patch.object(service, 'get_system_positions', return_value=system_positions):
            report = service.reconcile()

        assert report.drift_detected is True
        assert report.total_drift_usd > 0
        assert report.auto_close_triggered is True

    def test_get_system_positions(self, mock_session):
        """get_system_positions should query the DB and return PositionSummary dict."""
        from polyclaw.models import Position

        mock_pos = MagicMock(spec=Position)
        mock_pos.market_id = 'test-mkt'
        mock_pos.side = 'yes'
        mock_pos.quantity = 2.0
        mock_pos.notional_usd = 20.0
        mock_pos.avg_price = 0.4

        mock_session.scalars.return_value.all.return_value = [mock_pos]

        service = ReconciliationService(
            session=mock_session,
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
        )
        result = service.get_system_positions(mock_session)

        assert 'test-mkt' in result
        assert result['test-mkt'].quantity == 2.0
        assert result['test-mkt'].notional_usd == 20.0
        assert result['test-mkt'].side == 'yes'

    def test_get_api_positions_uses_polymarket_api(self):
        """get_api_positions reads from Polymarket API (polymarket_api provider)."""
        from unittest.mock import MagicMock
        svc = ReconciliationService(
            session=MagicMock(),
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
        )
        svc.polymarket_api.get_positions = MagicMock(return_value=[
            {'market_id': 'm1', 'side': 'yes', 'size': 10.0, 'value': 5.5}
        ])
        positions, available = svc.get_api_positions()
        assert available is True
        assert len(positions) == 1
        assert positions['m1'].source == 'POLYMARKET_API'
        assert positions['m1'].side == 'yes'
        assert positions['m1'].quantity == 10.0
        assert positions['m1'].notional_usd == 5.5
        svc.polymarket_api.get_positions.assert_called_once()

    def test_get_chain_positions_uses_ctf_contract(self):
        """get_chain_positions reads from CTF contract (ctf_provider)."""
        from unittest.mock import MagicMock
        svc = ReconciliationService(
            session=MagicMock(),
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
        )
        svc.ctf_provider.get_positions = MagicMock(return_value=[
            {'market_id': 'm1', 'side': 'yes', 'size': 10.0, 'value': 5.5}
        ])
        positions, available = svc.get_chain_positions()
        assert available is True
        assert len(positions) == 1
        assert positions['m1'].source == 'CTF_CONTRACT'
        assert positions['m1'].side == 'yes'
        assert positions['m1'].quantity == 10.0
        assert positions['m1'].notional_usd == 5.5
        svc.ctf_provider.get_positions.assert_called_once()

    def test_can_trade_live_blocks_when_api_unavailable(self):
        """can_trade_live returns False when API positions unavailable."""
        from polyclaw.reconciliation.service import ReconciliationService
        svc = ReconciliationService(
            session=MagicMock(),
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
            mode='live',
        )
        with patch.object(svc, 'get_api_positions', return_value=({}, False)):
            with patch.object(svc, 'get_chain_positions', return_value=({}, True)):
                allowed, reason = svc.can_trade_live()
        assert allowed is False
        assert 'API positions unavailable' in reason

    def test_can_trade_live_blocks_when_chain_unavailable(self):
        """can_trade_live returns False when chain positions unavailable."""
        from polyclaw.reconciliation.service import ReconciliationService
        svc = ReconciliationService(
            session=MagicMock(),
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
            mode='live',
        )
        with patch.object(svc, 'get_api_positions', return_value=({}, True)):
            with patch.object(svc, 'get_chain_positions', return_value=({}, False)):
                allowed, reason = svc.can_trade_live()
        assert allowed is False
        assert 'chain positions unavailable' in reason

    def test_can_trade_live_allows_paper_mode(self):
        """can_trade_live allows when mode is paper (no gating)."""
        from polyclaw.reconciliation.service import ReconciliationService
        svc = ReconciliationService(
            session=MagicMock(),
            ctf_provider=MagicMock(),
            polymarket_api=MagicMock(),
            mode='paper',
        )
        with patch.object(svc, 'get_api_positions', return_value=({}, False)):
            with patch.object(svc, 'get_chain_positions', return_value=({}, False)):
                allowed, reason = svc.can_trade_live()
        assert allowed is True
        assert 'not in live mode' in reason


# ---------------------------------------------------------------------------
# DriftAlerts tests
# ---------------------------------------------------------------------------

class TestDriftAlerts:
    @pytest.fixture
    def mock_session(self):
        return MagicMock()

    def test_warning_severity_below_threshold(self, mock_session):
        """total_drift_usd < 5 should produce WARNING severity."""
        alerts = DriftAlerts()
        report = ReconciliationReport(
            drift_detected=True,
            total_drift_usd=3.0,
            discrepancy_items=[
                DiscrepancyItem(
                    market_id='mkt-1',
                    source1='SYSTEM_DB',
                    source2='CTF_CONTRACT',
                    expected_value=10.0,
                    actual_value=7.0,
                    drift_usd=3.0,
                )
            ],
            timestamp=utcnow(),
            auto_close_triggered=False,
            auto_close_count=0,
        )

        severity = alerts.send_drift_alert(mock_session, report)

        assert severity == DriftSeverity.WARNING

    def test_critical_severity_at_or_above_threshold(self, mock_session):
        """total_drift_usd >= 5 should produce CRITICAL severity."""
        alerts = DriftAlerts()
        report = ReconciliationReport(
            drift_detected=True,
            total_drift_usd=5.0,
            discrepancy_items=[],
            timestamp=utcnow(),
            auto_close_triggered=False,
            auto_close_count=0,
        )

        severity = alerts.send_drift_alert(mock_session, report)

        assert severity == DriftSeverity.CRITICAL

    def test_critical_triggers_notification(self, mock_session):
        """CRITICAL alerts should call the notification service."""
        alerts = DriftAlerts()
        report = ReconciliationReport(
            drift_detected=True,
            total_drift_usd=10.0,
            discrepancy_items=[
                DiscrepancyItem(
                    market_id='mkt-1',
                    source1='SYSTEM_DB',
                    source2='CTF_CONTRACT',
                    expected_value=20.0,
                    actual_value=10.0,
                    drift_usd=10.0,
                )
            ],
            timestamp=utcnow(),
            auto_close_triggered=False,
            auto_close_count=0,
        )

        with patch.object(alerts.notification_service, 'notify') as mock_notify:
            severity = alerts.send_drift_alert(mock_session, report)

        assert severity == DriftSeverity.CRITICAL
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert call_args[1]['channel'] == 'reconciliation_alert'

    def test_warning_does_not_trigger_notification(self, mock_session):
        """WARNING alerts should NOT call the notification service."""
        alerts = DriftAlerts()
        report = ReconciliationReport(
            drift_detected=True,
            total_drift_usd=2.0,
            discrepancy_items=[
                DiscrepancyItem(
                    market_id='mkt-1',
                    source1='SYSTEM_DB',
                    source2='POLYMARKET_API',
                    expected_value=10.0,
                    actual_value=8.0,
                    drift_usd=2.0,
                )
            ],
            timestamp=utcnow(),
            auto_close_triggered=False,
            auto_close_count=0,
        )

        with patch.object(alerts.notification_service, 'notify') as mock_notify:
            severity = alerts.send_drift_alert(mock_session, report)

        assert severity == DriftSeverity.WARNING
        mock_notify.assert_not_called()
