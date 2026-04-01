"""Tests for on-chain analysis module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from polyclaw.data.onchain import (
    OnChainAnalyzer,
    WhalePosition,
    WalletActivity,
    UnusualActivity,
)


class TestDataClasses:
    def test_whale_position(self):
        wp = WhalePosition('0xabc', 'm-1', 'yes', 5000.0, 7500.0)
        assert wp.wallet_address == '0xabc'
        assert wp.side == 'yes'
        assert wp.size_usd == 5000.0

    def test_wallet_activity(self):
        wa = WalletActivity('0xdef', 'm-2', 'no', 2000.0, datetime.utcnow(), 'whale')
        assert wa.label == 'whale'

    def test_unusual_activity(self):
        ua = UnusualActivity('m-3', 'volume_spike', 0.8, 'yes', '10x normal')
        assert ua.activity_type == 'volume_spike'


class TestOnChainAnalyzer:
    def test_init_and_close(self):
        a = OnChainAnalyzer()
        assert a._rpc_url
        a.close()
        assert a._http_client is None

    def test_get_large_positions_empty(self):
        a = OnChainAnalyzer()
        with patch.object(a, '_fetch_market_positions', return_value=[]):
            assert a.get_large_positions(['m-1']) == []

    def test_get_large_positions_filters_by_size(self):
        a = OnChainAnalyzer()
        whales = [
            WhalePosition('0xa', 'm-1', 'yes', 500.0, 500.0),
            WhalePosition('0xb', 'm-1', 'no', 5000.0, 5000.0),
        ]
        with patch.object(a, '_fetch_market_positions', return_value=whales):
            result = a.get_large_positions(['m-1'], min_usd=1000.0)
            assert len(result) == 1
            assert result[0].wallet_address == '0xb'

    def test_get_large_positions_respects_max_wallets(self):
        a = OnChainAnalyzer()
        whales = [WhalePosition(f'0x{i}', 'm-1', 'yes', 5000.0, 5000.0) for i in range(20)]
        with patch.object(a, '_fetch_market_positions', return_value=whales):
            result = a.get_large_positions(['m-1'], max_wallets=5)
            assert len(result) == 5

    def test_get_large_positions_sorts_by_size(self):
        a = OnChainAnalyzer()
        whales = [
            WhalePosition('0xa', 'm-1', 'yes', 3000.0, 3000.0),
            WhalePosition('0xb', 'm-1', 'no', 8000.0, 8000.0),
            WhalePosition('0xc', 'm-1', 'yes', 5000.0, 5000.0),
        ]
        with patch.object(a, '_fetch_market_positions', return_value=whales):
            result = a.get_large_positions(['m-1'])
            assert result[0].size_usd == 8000.0
            assert result[1].size_usd == 5000.0
            assert result[2].size_usd == 3000.0

    def test_track_known_wallets_with_balances(self):
        a = OnChainAnalyzer()
        # wallet1 has yes=1M, no=0; wallet2 has yes=0, no=2M
        balances = {(w, m, o): 0 for w in ['0xw1', '0xw2'] for m in ['m-1'] for o in [0, 1]}
        balances[('0xw1', 'm-1', 1)] = 1_000_000  # yes
        balances[('0xw2', 'm-1', 0)] = 2_000_000  # no

        def mock_balance(trader, market, outcome):
            return balances.get((trader, market, outcome), 0)

        with patch.object(a, '_query_ctf_balance', side_effect=mock_balance):
            result = a.track_known_wallets(['0xw1', '0xw2'], ['m-1'])
            assert len(result) == 2
            sides = {r.wallet_address: r.side for r in result}
            assert sides['0xw1'] == 'yes'
            assert sides['0xw2'] == 'no'

    def test_track_known_wallets_empty_when_zero_balances(self):
        a = OnChainAnalyzer()
        with patch.object(a, '_query_ctf_balance', return_value=0):
            assert a.track_known_wallets(['0xw'], ['m-1']) == []

    def test_detect_unusual_activity_handles_rpc_failure(self):
        a = OnChainAnalyzer()
        with patch.object(a, '_rpc_call', side_effect=Exception('RPC down')):
            assert a.detect_unusual_activity(['m-1']) == []

    def test_fetch_market_positions_returns_empty_without_url(self):
        a = OnChainAnalyzer()
        with patch('polyclaw.data.onchain.settings') as mock_settings:
            mock_settings.polymarket_positions_url = ''
            result = a._fetch_market_positions('m-1', 1000.0)
            assert result == []
