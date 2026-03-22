"""
Tests for the health check module.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from polyclaw.monitoring.health import (
    ComponentHealth,
    ComponentStatus,
    HealthChecker,
    HealthStatus,
)
from polyclaw.timeutils import utcnow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def mock_ctf_provider():
    return MagicMock()


@pytest.fixture
def mock_polymarket_api():
    return MagicMock()


# ---------------------------------------------------------------------------
# ComponentHealth and HealthStatus dataclass tests
# ---------------------------------------------------------------------------

class TestComponentHealth:
    def test_all_fields_present(self):
        ch = ComponentHealth(
            component_name='database',
            status=ComponentStatus.HEALTHY,
            latency_ms=12.5,
            error_message=None,
        )
        assert ch.component_name == 'database'
        assert ch.status == ComponentStatus.HEALTHY
        assert ch.latency_ms == 12.5
        assert ch.error_message is None

    def test_with_error_message(self):
        ch = ComponentHealth(
            component_name='database',
            status=ComponentStatus.UNHEALTHY,
            latency_ms=500.0,
            error_message='connection refused',
        )
        assert ch.status == ComponentStatus.UNHEALTHY
        assert ch.error_message == 'connection refused'


class TestHealthStatus:
    def test_health_status_fields(self):
        ts = utcnow()
        ch = ComponentHealth(
            component_name='database',
            status=ComponentStatus.HEALTHY,
            latency_ms=10.0,
        )
        status = HealthStatus(
            overall_status=ComponentStatus.HEALTHY,
            checks=[ch],
            timestamp=ts,
        )
        assert status.overall_status == ComponentStatus.HEALTHY
        assert len(status.checks) == 1
        assert status.timestamp == ts


# ---------------------------------------------------------------------------
# ComponentStatus enum tests
# ---------------------------------------------------------------------------

class TestComponentStatus:
    def test_status_values(self):
        assert ComponentStatus.HEALTHY.value == 'healthy'
        assert ComponentStatus.DEGRADED.value == 'degraded'
        assert ComponentStatus.UNHEALTHY.value == 'unhealthy'


# ---------------------------------------------------------------------------
# HealthChecker tests
# ---------------------------------------------------------------------------

class TestHealthCheckerInit:
    def test_init_stores_dependencies(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        checker = HealthChecker(
            session=mock_session,
            ctf_provider=mock_ctf_provider,
            polymarket_api=mock_polymarket_api,
        )
        assert checker.session is mock_session
        assert checker.ctf_provider is mock_ctf_provider
        assert checker.polymarket_api is mock_polymarket_api

    def test_init_creates_default_providers(self, mock_session):
        checker = HealthChecker(session=mock_session)
        # Should create default instances without error
        assert checker.ctf_provider is not None
        assert checker.polymarket_api is not None


class TestCheckDatabase:
    def test_database_healthy_on_success(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.return_value = None
        mock_session.commit.return_value = None

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_database()

        assert result.component_name == 'database'
        assert result.status == ComponentStatus.HEALTHY
        assert result.latency_ms >= 0
        assert result.error_message is None

    def test_database_unhealthy_on_exception(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.side_effect = Exception('connection refused')

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_database()

        assert result.component_name == 'database'
        assert result.status == ComponentStatus.UNHEALTHY
        assert result.latency_ms >= 0
        assert 'connection refused' in result.error_message


class TestCheckPolymarketApi:
    def test_api_healthy_on_success(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_polymarket_api.list_markets.return_value = []

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_polymarket_api()

        assert result.component_name == 'polymarket_api'
        assert result.status == ComponentStatus.HEALTHY
        assert result.latency_ms >= 0
        mock_polymarket_api.list_markets.assert_called_once_with(limit=1)

    def test_api_unhealthy_on_exception(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_polymarket_api.list_markets.side_effect = Exception('timeout')

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_polymarket_api()

        assert result.component_name == 'polymarket_api'
        assert result.status == ComponentStatus.UNHEALTHY
        assert 'timeout' in result.error_message


class TestCheckCtfContract:
    def test_ctf_healthy_on_success(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_ctf_provider._rpc_call.return_value = '0x1234'

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_ctf_contract()

        assert result.component_name == 'ctf_contract'
        assert result.status == ComponentStatus.HEALTHY
        assert result.latency_ms >= 0
        mock_ctf_provider._rpc_call.assert_called_once_with('eth_blockNumber', [])

    def test_ctf_unhealthy_on_rpc_failure(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_ctf_provider._rpc_call.side_effect = Exception('RPC error')

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_ctf_contract()

        assert result.component_name == 'ctf_contract'
        assert result.status == ComponentStatus.UNHEALTHY
        assert 'RPC error' in result.error_message

    def test_ctf_unhealthy_on_null_result(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_ctf_provider._rpc_call.return_value = None

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_ctf_contract()

        assert result.component_name == 'ctf_contract'
        assert result.status == ComponentStatus.UNHEALTHY
        assert 'null' in result.error_message


class TestCheckDataFreshness:
    def test_data_freshness_healthy(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        # Latest data is 5 minutes old (within 10 min threshold)
        recent = utcnow() - timedelta(minutes=5)
        mock_session.scalar.return_value = recent

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_data_freshness()

        assert result.component_name == 'data_freshness'
        assert result.status == ComponentStatus.HEALTHY
        assert result.error_message is None

    def test_data_freshness_unhealthy_when_stale(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        # Latest data is 20 minutes old (exceeds 10 min threshold)
        stale = utcnow() - timedelta(minutes=20)
        mock_session.scalar.return_value = stale

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_data_freshness()

        assert result.component_name == 'data_freshness'
        assert result.status == ComponentStatus.UNHEALTHY
        assert '20' in result.error_message
        assert 'minutes old' in result.error_message

    def test_data_freshness_degraded_when_no_data(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.scalar.return_value = None

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_data_freshness()

        assert result.component_name == 'data_freshness'
        assert result.status == ComponentStatus.DEGRADED
        assert 'No market data' in result.error_message


class TestCheckKillSwitch:
    def test_kill_switch_healthy_when_disabled(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_row = MagicMock()
        mock_row.result = 'disabled'
        mock_row.payload = ''
        mock_session.scalar.return_value = mock_row

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_kill_switch()

        assert result.component_name == 'kill_switch'
        assert result.status == ComponentStatus.HEALTHY
        assert result.error_message is None

    def test_kill_switch_unhealthy_when_enabled(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_row = MagicMock()
        mock_row.result = 'enabled'
        mock_row.payload = 'manual stop'
        mock_session.scalar.return_value = mock_row

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        result = checker.check_kill_switch()

        assert result.component_name == 'kill_switch'
        assert result.status == ComponentStatus.UNHEALTHY
        assert 'ACTIVE' in result.error_message


class TestCheckOverall:
    def test_overall_healthy_when_all_pass(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.return_value = None
        mock_session.commit.return_value = None
        # scalar is called twice: check_data_freshness (datetime), check_kill_switch (mock row)
        mock_row = MagicMock()
        mock_row.result = 'disabled'
        mock_row.payload = ''
        mock_session.scalar.side_effect = [
            utcnow() - timedelta(minutes=2),  # data freshness
            mock_row,                          # kill switch
        ]
        mock_polymarket_api.list_markets.return_value = []
        mock_ctf_provider._rpc_call.return_value = '0x1'

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        status = checker.check()

        assert status.overall_status == ComponentStatus.HEALTHY
        assert len(status.checks) == 5

    def test_overall_degraded_when_one_degraded(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.return_value = None
        mock_session.commit.return_value = None
        # First scalar call: data freshness (degraded - no data)
        # Subsequent scalar calls: kill switch
        mock_row_disabled = MagicMock()
        mock_row_disabled.result = 'disabled'
        mock_row_disabled.payload = ''
        mock_session.scalar.side_effect = [None, mock_row_disabled]
        mock_polymarket_api.list_markets.return_value = []
        mock_ctf_provider._rpc_call.return_value = '0x1'

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        status = checker.check()

        assert status.overall_status == ComponentStatus.DEGRADED

    def test_overall_unhealthy_when_one_unhealthy(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.side_effect = Exception('DB error')
        mock_session.scalar.side_effect = [None]
        mock_polymarket_api.list_markets.return_value = []
        mock_ctf_provider._rpc_call.return_value = '0x1'

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        status = checker.check()

        assert status.overall_status == ComponentStatus.UNHEALTHY

    def test_timestamp_is_set(self, mock_session, mock_ctf_provider, mock_polymarket_api):
        mock_session.execute.return_value = None
        mock_session.commit.return_value = None
        mock_session.scalar.return_value = utcnow()
        mock_polymarket_api.list_markets.return_value = []
        mock_ctf_provider._rpc_call.return_value = '0x1'

        checker = HealthChecker(mock_session, mock_ctf_provider, mock_polymarket_api)
        status = checker.check()

        assert status.timestamp is not None
        assert isinstance(status.timestamp, datetime)
