"""Tests for market whitelist (Week 9.2)."""

import pytest

from polyclaw.execution.whitelist import MarketWhitelist


class TestMarketWhitelist:
    def test_add_to_whitelist(self, db_session):
        """add_to_whitelist() adds a market and persists it."""
        wl = MarketWhitelist(db_session=db_session)
        result = wl.add_to_whitelist('test-market-1', reason='manual_test')
        assert result is True

        # Verify in DB
        whitelist = wl.get_whitelist()
        assert 'test-market-1' in whitelist

    def test_add_duplicate_returns_false(self, db_session):
        """add_to_whitelist() returns False for duplicate market."""
        wl = MarketWhitelist(db_session=db_session)
        wl.add_to_whitelist('dup-market')
        result = wl.add_to_whitelist('dup-market')
        assert result is False

    def test_remove_from_whitelist(self, db_session):
        """remove_from_whitelist() removes a market from the whitelist."""
        wl = MarketWhitelist(db_session=db_session)
        wl.add_to_whitelist('remove-test')
        result = wl.remove_from_whitelist('remove-test')
        assert result is True

        whitelist = wl.get_whitelist()
        assert 'remove-test' not in whitelist

    def test_remove_nonexistent_returns_false(self, db_session):
        """remove_from_whitelist() returns False for nonexistent market."""
        wl = MarketWhitelist(db_session=db_session)
        result = wl.remove_from_whitelist('nonexistent')
        assert result is False

    def test_is_allowed_explicit_whitelist(self, db_session):
        """is_allowed() returns True for explicitly whitelisted market."""
        wl = MarketWhitelist(db_session=db_session)
        wl.add_to_whitelist('whitelisted-market')
        check = wl.is_allowed('whitelisted-market')
        assert check.allowed is True
        assert check.source == 'whitelist'

    def test_is_allowed_meets_expand_criteria(self, db_session):
        """is_allowed() returns True for market meeting expand criteria."""
        wl = MarketWhitelist(db_session=db_session)
        check = wl.is_allowed(
            'expand-market',
            liquidity_usd=100_000.0,  # > $50K
            spread_bps=100,  # < 200 bps
        )
        assert check.allowed is True
        assert check.source == 'expand'

    def test_is_allowed_blocked_by_liquidity(self, db_session):
        """is_allowed() blocks market with insufficient liquidity."""
        wl = MarketWhitelist(db_session=db_session)
        check = wl.is_allowed(
            'low-liquidity',
            liquidity_usd=10_000.0,  # < $50K
            spread_bps=100,
        )
        assert check.allowed is False
        assert check.source == 'blocked'

    def test_is_allowed_blocked_by_spread(self, db_session):
        """is_allowed() blocks market with excessive spread."""
        wl = MarketWhitelist(db_session=db_session)
        check = wl.is_allowed(
            'wide-spread',
            liquidity_usd=100_000.0,
            spread_bps=300,  # > 200 bps
        )
        assert check.allowed is False
        assert check.source == 'blocked'

    def test_is_allowed_no_market_data(self, db_session):
        """is_allowed() returns blocked when no market data provided."""
        wl = MarketWhitelist(db_session=db_session)
        check = wl.is_allowed('unknown-market')
        assert check.allowed is False
        assert check.source == 'blocked'

    def test_is_allowed_custom_thresholds(self, db_session):
        """is_allowed() uses custom thresholds from config."""
        wl = MarketWhitelist(
            db_session=db_session,
            config={'min_liquidity_usd': 10_000.0, 'max_spread_bps': 500},
        )
        # With custom thresholds, this market should pass
        check = wl.is_allowed(
            'custom-market',
            liquidity_usd=15_000.0,
            spread_bps=400,
        )
        assert check.allowed is True
        assert check.source == 'expand'

    def test_get_whitelist_empty(self, db_session):
        """get_whitelist() returns empty list when no markets whitelisted."""
        wl = MarketWhitelist(db_session=db_session)
        assert wl.get_whitelist() == []

    def test_sync_from_db(self, db_session):
        """sync_from_db() updates the session reference."""
        wl = MarketWhitelist(db_session=db_session)
        wl.add_to_whitelist('sync-test')
        wl.sync_from_db(db_session)
        # Should not raise
        wl.get_whitelist()

    def test_no_session_raises(self, db_session):
        """Operations raise RuntimeError when no session is set."""
        wl = MarketWhitelist(db_session=None)
        with pytest.raises(RuntimeError, match='No database session'):
            wl.get_whitelist()
