"""Tests for walk-forward validation."""

from datetime import date, timedelta

import pytest

from polyclaw.backtest.walkforward import WalkForwardResult, WalkForwardValidator, WindowResult
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.timeutils import utcnow


class AlwaysSignalStrategy(BaseStrategy):
    """Strategy that always generates a signal."""

    strategy_id: str = 'always_signal'
    name: str = 'Always Signal'
    version: str = '1.0.0'

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {'yes_price': market.yes_price}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        return Signal(
            strategy_id=self.strategy_id,
            side=Side.YES,
            confidence=0.75,
            edge_bps=1000,
            explanation='always signal',
            features_used=features,
        )


class NeverSignalStrategy(BaseStrategy):
    """Strategy that never generates signals."""

    strategy_id: str = 'never_signal'
    name: str = 'Never Signal'
    version: str = '1.0.0'

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        return None


def make_snapshots(n: int, start_offset: int = 0) -> list[MarketSnapshot]:
    now = utcnow()
    return [
        MarketSnapshot(
            market_id='m1',
            title='Test',
            description='test',
            yes_price=0.5,
            no_price=0.5,
            spread_bps=150,
            liquidity_usd=10000,
            volume_24h_usd=5000,
            category='test',
            event_key='test',
            closes_at=now + timedelta(days=30),
            fetched_at=now + timedelta(days=start_offset + i),
        )
        for i in range(n)
    ]


def test_walkforward_empty_data():
    validator = WalkForwardValidator(strategy=AlwaysSignalStrategy())
    result = validator.run([])
    assert result.total_windows == 0
    assert result.avg_sharpe == 0.0
    assert result.pass_gate is False


def test_walkforward_single_window():
    validator = WalkForwardValidator(
        strategy=AlwaysSignalStrategy(),
        train_days=10,
        test_days=5,
    )
    data = make_snapshots(20)
    result = validator.run(data)
    assert result.total_windows >= 1


def test_walkforward_aggregates_metrics():
    validator = WalkForwardValidator(
        strategy=AlwaysSignalStrategy(),
        train_days=5,
        test_days=5,
    )
    data = make_snapshots(30)
    result = validator.run(data)
    assert isinstance(result.avg_sharpe, float)
    assert isinstance(result.avg_max_dd, float)
    assert isinstance(result.avg_win_rate, float)
    assert isinstance(result.pass_gate, bool)


def test_walkforward_no_signals():
    validator = WalkForwardValidator(
        strategy=NeverSignalStrategy(),
        train_days=5,
        test_days=5,
    )
    data = make_snapshots(20)
    result = validator.run(data)
    assert result.total_windows >= 1
    # With no signals, trades are 0, metrics should be 0
    for w in result.windows:
        assert w.total_trades == 0


def test_walkforward_window_result():
    wr = WindowResult(
        window_index=0,
        train_start=0,
        train_end=10,
        test_start=10,
        test_end=15,
        train_samples=10,
        test_samples=5,
        total_pnl=100.0,
        sharpe_ratio=0.8,
        max_drawdown=0.05,
        win_rate=0.6,
        total_trades=3,
    )
    assert wr.window_index == 0
    assert wr.total_trades == 3
    assert wr.sharpe_ratio == 0.8


def test_walkforward_pass_gate():
    validator = WalkForwardValidator(
        strategy=AlwaysSignalStrategy(),
        train_days=5,
        test_days=5,
        gate_sharpe=0.0,
        gate_max_dd=1.0,
    )
    data = make_snapshots(20)
    result = validator.run(data)
    # With zero-threshold gate, should pass if it runs
    assert isinstance(result.pass_gate, bool)


def test_walkforward_result_dataclass():
    result = WalkForwardResult(
        windows=[],
        avg_sharpe=0.5,
        avg_max_dd=0.1,
        avg_win_rate=0.55,
        pass_gate=True,
        total_windows=3,
    )
    assert result.avg_sharpe == 0.5
    assert result.pass_gate is True
    assert result.total_windows == 3
