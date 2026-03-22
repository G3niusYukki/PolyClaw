"""
Tests for the anomaly detection module.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from polyclaw.monitoring.anomaly import (
    AnomalyDetector,
    AnomalyResult,
    AnomalySeverity,
)

# ---------------------------------------------------------------------------
# Helper: lightweight row-like object for SQLAlchemy results
# ---------------------------------------------------------------------------

class _Row:
    """Minimal row-like object mimicking SQLAlchemy result rows."""
    __slots__ = ('day', 'daily_pnl')

    def __init__(self, day, daily_pnl):
        self.day = day
        self.daily_pnl = daily_pnl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    return MagicMock()


# ---------------------------------------------------------------------------
# AnomalyDetector tests
# ---------------------------------------------------------------------------

class TestAnomalyDetectorInit:
    def test_init_stores_session(self, mock_session):
        detector = AnomalyDetector(mock_session)
        assert detector.session is mock_session


class TestDetectPnlSpike:
    def test_no_anomaly_when_within_bounds(self, mock_session):
        """PnL within mean +/- 3*std should not trigger a spike."""
        mock_session.execute.return_value.all.return_value = [
            _Row(day=datetime(2026, 3, i).date(), daily_pnl=10.0 + (i % 3))
            for i in range(1, 6)
        ]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_pnl_spike()

        assert is_anomaly is False
        assert reason is None

    def test_anomaly_detected_on_pnl_spike_up(self, mock_session):
        """PnL significantly above upper bound should trigger CRITICAL anomaly."""
        # 29 days of $10 pnl + 1 day of $100 pnl (massive spike)
        rows = [_Row(day=datetime(2026, 3, i).date(), daily_pnl=10.0) for i in range(1, 31)]
        rows.append(_Row(day=datetime(2026, 3, 31).date(), daily_pnl=100.0))
        mock_session.execute.return_value.all.return_value = rows

        with patch.object(AnomalyDetector, '_emit_critical_alert') as mock_alert:
            detector = AnomalyDetector(mock_session)
            is_anomaly, reason = detector.detect_pnl_spike()

        assert is_anomaly is True
        assert reason is not None
        assert 'pnl_spike' in reason
        mock_alert.assert_called_once()

    def test_anomaly_detected_on_pnl_spike_down(self, mock_session):
        """PnL significantly below lower bound should trigger CRITICAL anomaly."""
        # 30 days of $100 pnl + 1 day of $1 pnl (massive spike down)
        rows = [_Row(day=datetime(2026, 3, i).date(), daily_pnl=100.0) for i in range(1, 31)]
        rows.append(_Row(day=datetime(2026, 3, 31).date(), daily_pnl=1.0))
        mock_session.execute.return_value.all.return_value = rows

        with patch.object(AnomalyDetector, '_emit_critical_alert') as mock_alert:
            detector = AnomalyDetector(mock_session)
            is_anomaly, reason = detector.detect_pnl_spike()

        assert is_anomaly is True
        assert reason is not None
        assert 'pnl_spike' in reason
        mock_alert.assert_called_once()

    def test_no_anomaly_insufficient_data(self, mock_session):
        """Fewer than 2 days of data should return no anomaly."""
        mock_session.execute.return_value.all.return_value = [
            _Row(day=datetime(2026, 3, 1).date(), daily_pnl=10.0),
        ]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_pnl_spike()

        assert is_anomaly is False
        assert reason is None

    def test_no_anomaly_when_all_identical(self, mock_session):
        """When all PnL values are identical (std=0), no spike is possible."""
        rows = [_Row(day=datetime(2026, 3, i).date(), daily_pnl=10.0) for i in range(1, 31)]
        rows.append(_Row(day=datetime(2026, 3, 31).date(), daily_pnl=10.0))
        mock_session.execute.return_value.all.return_value = rows

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_pnl_spike()

        # With std=0, the early return handles it
        assert is_anomaly is False


class TestDetectVolumeAnomaly:
    def test_no_anomaly_when_volume_normal(self, mock_session):
        """Volume within 3x rolling average should not trigger anomaly."""
        mock_session.scalar.side_effect = [1000.0, 2000.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_volume_anomaly('market-1')

        assert is_anomaly is False
        assert reason is None

    def test_anomaly_detected_when_volume_exceeds_threshold(self, mock_session):
        """Volume > 3x rolling average should trigger WARNING anomaly."""
        mock_session.scalar.side_effect = [1000.0, 3500.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_volume_anomaly('market-1')

        assert is_anomaly is True
        assert reason is not None
        assert 'volume_anomaly' in reason
        assert 'market-1' in reason

    def test_no_anomaly_when_no_historical_data(self, mock_session):
        """No historical data should not trigger anomaly."""
        mock_session.scalar.side_effect = [None, 100.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_volume_anomaly('market-1')

        assert is_anomaly is False

    def test_no_anomaly_when_rolling_avg_is_zero(self, mock_session):
        """Rolling average of zero should not trigger anomaly."""
        mock_session.scalar.side_effect = [0.0, 100.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_volume_anomaly('market-1')

        assert is_anomaly is False


class TestDetectSpreadAnomaly:
    def test_no_anomaly_when_spread_normal(self, mock_session):
        """Spread within 3x rolling average should not trigger anomaly."""
        mock_session.scalar.side_effect = [50.0, 100.0]  # avg=50, current=100 (2x, below 3x)

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_spread_anomaly('market-1')

        assert is_anomaly is False
        assert reason is None

    def test_anomaly_detected_when_spread_exceeds_threshold(self, mock_session):
        """Spread > 3x rolling average should trigger WARNING anomaly."""
        mock_session.scalar.side_effect = [50.0, 200.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_spread_anomaly('market-1')

        assert is_anomaly is True
        assert reason is not None
        assert 'spread_anomaly' in reason
        assert 'market-1' in reason

    def test_no_anomaly_when_no_historical_data(self, mock_session):
        """No historical data should not trigger anomaly."""
        mock_session.scalar.side_effect = [None, 100.0]

        detector = AnomalyDetector(mock_session)
        is_anomaly, reason = detector.detect_spread_anomaly('market-1')

        assert is_anomaly is False


class TestRunAll:
    def test_run_all_returns_list(self, mock_session):
        """run_all should return a list of AnomalyResult objects."""
        mock_session.execute.return_value.all.return_value = []
        mock_session.scalars.return_value.all.return_value = []

        detector = AnomalyDetector(mock_session)
        results = detector.run_all()

        assert isinstance(results, list)
        assert all(isinstance(r, AnomalyResult) for r in results)

    def test_run_all_includes_volume_anomaly(self, mock_session):
        """run_all should detect volume anomalies for active markets."""
        mock_session.execute.return_value.all.return_value = []
        mock_session.scalars.return_value.all.return_value = ['mkt-1']
        mock_session.scalar.side_effect = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        with patch.object(AnomalyDetector, '_emit_critical_alert'):
            # Patch detect_volume_anomaly to always return an anomaly
            with patch.object(
                AnomalyDetector, 'detect_volume_anomaly',
                return_value=(True, 'volume_anomaly: current_vol=$3500 > 3x_rolling_avg=$1000')
            ):
                with patch.object(
                    AnomalyDetector, 'detect_spread_anomaly',
                    return_value=(False, None)
                ):
                    detector = AnomalyDetector(mock_session)
                    results = detector.run_all()

        anomaly_types = [r.detector_type for r in results]
        assert 'volume_anomaly' in anomaly_types
        vol_result = next(r for r in results if r.detector_type == 'volume_anomaly')
        assert vol_result.market_id == 'mkt-1'
        assert vol_result.severity == AnomalySeverity.WARNING

    def test_run_all_returns_empty_when_no_anomalies(self, mock_session):
        """run_all returns empty list when no anomalies are detected."""
        mock_session.execute.return_value.all.return_value = []
        mock_session.scalars.return_value.all.return_value = ['mkt-1']
        mock_session.scalar.side_effect = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        with patch.object(AnomalyDetector, '_emit_critical_alert'):
            with patch.object(AnomalyDetector, 'detect_volume_anomaly', return_value=(False, None)):
                with patch.object(AnomalyDetector, 'detect_spread_anomaly', return_value=(False, None)):
                    detector = AnomalyDetector(mock_session)
                    results = detector.run_all()

        assert results == []


class TestAnomalyResult:
    def test_anomaly_result_dataclass_fields(self):
        """AnomalyResult should have all required fields."""
        result = AnomalyResult(
            detector_type='pnl_spike',
            market_id=None,
            expected=10.0,
            actual=50.0,
            severity=AnomalySeverity.CRITICAL,
            reason='pnl_spike: today=$50',
        )
        assert result.detector_type == 'pnl_spike'
        assert result.market_id is None
        assert result.expected == 10.0
        assert result.actual == 50.0
        assert result.severity == AnomalySeverity.CRITICAL
        assert 'pnl_spike' in result.reason


class TestAnomalySeverity:
    def test_severity_values(self):
        """AnomalySeverity enum should have WARNING and CRITICAL values."""
        assert AnomalySeverity.WARNING.value == 'WARNING'
        assert AnomalySeverity.CRITICAL.value == 'CRITICAL'
