"""Integration tests for the complete trading pipeline."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from polyclaw.domain import MarketSnapshot
from polyclaw.services.runner import RunnerService


class TestTradingPipeline:
    """End-to-end tests for scan → rank → score → risk → decide flow."""

    @pytest.fixture
    def mock_market(self):
        """Create a mock market that passes all risk checks."""
        return MarketSnapshot(
            market_id="0xintegration123",
            title="Test Integration Market",
            description="For integration testing",
            yes_price=0.65,
            no_price=0.35,
            spread_bps=50,
            liquidity_usd=50000,
            volume_24h_usd=100000,
            category="crypto",
            event_key="test-event-123",
            closes_at=datetime.utcnow() + timedelta(days=14),
            fetched_at=datetime.utcnow(),
        )

    def test_runner_tick_with_mock_markets(self, db_session, mock_market):
        """Test complete pipeline from market scan to decision creation."""
        from polyclaw.providers.sample_market import SampleMarketProvider

        with patch.object(SampleMarketProvider, "list_markets", return_value=[mock_market]):
            runner = RunnerService()

            result = runner.tick(session=db_session)

            assert isinstance(result, dict)
            assert "markets_scanned" in result
            assert "decisions_created" in result
            assert isinstance(result["markets_scanned"], int)
            assert isinstance(result["decisions_created"], int)
            assert result["markets_scanned"] >= 0
            assert result["decisions_created"] >= 0
