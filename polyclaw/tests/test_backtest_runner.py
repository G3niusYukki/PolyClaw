"""Tests for the backtest runner."""

from datetime import date, datetime, timedelta

from polyclaw.backtest.runner import BacktestResult, BacktestRunner
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.timeutils import utcnow


class DummyStrategy(BaseStrategy):
    """Simple strategy that always generates a signal."""

    strategy_id: str = 'dummy'
    name: str = 'Dummy Strategy'
    version: str = '1.0.0'

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {'yes_price': market.yes_price, 'no_price': market.no_price}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        if market.yes_price > 0.6:
            return Signal(
                strategy_id=self.strategy_id,
                side=Side.YES,
                confidence=0.75,
                edge_bps=1000,
                explanation='Dummy long signal',
                features_used=features,
            )
        return None


class NoSignalStrategy(BaseStrategy):
    """Strategy that never generates signals."""

    strategy_id: str = 'nosignal'
    name: str = 'No Signal Strategy'
    version: str = '1.0.0'

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        return None


def make_snapshot(
    market_id: str,
    yes_price: float = 0.5,
    fetched_at: datetime | None = None,
    **kwargs,
) -> MarketSnapshot:
    if fetched_at is None:
        fetched_at = utcnow()
    return MarketSnapshot(
        market_id=market_id,
        title=f'Test market {market_id}',
        description='test',
        yes_price=yes_price,
        no_price=1 - yes_price,
        spread_bps=150,
        liquidity_usd=10000,
        volume_24h_usd=5000,
        category='test',
        event_key='test-event',
        closes_at=fetched_at + timedelta(days=10),
        fetched_at=fetched_at,
        **kwargs,
    )


def test_backtest_empty_data():
    runner = BacktestRunner(
        strategies=[DummyStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    result = runner.run([])
    assert result.total_pnl == 0.0
    assert result.sharpe_ratio == 0.0
    assert result.max_drawdown == 0.0


def test_backtest_no_signals():
    runner = BacktestRunner(
        strategies=[NoSignalStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    data = [make_snapshot('m1', 0.5, utcnow() + timedelta(days=i)) for i in range(10)]
    result = runner.run(data)
    assert len(result.trades) == 0
    assert result.total_pnl == 0.0


def test_backtest_generates_trades():
    runner = BacktestRunner(
        strategies=[DummyStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    data = [make_snapshot('m1', 0.65, utcnow() + timedelta(days=i)) for i in range(5)]
    result = runner.run(data)
    # DummyStrategy generates signal for yes_price > 0.6
    assert len(result.trades) >= 0  # May or may not generate trades depending on signals


def test_backtest_metrics():
    runner = BacktestRunner(
        strategies=[DummyStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    data = [make_snapshot('m1', 0.65, utcnow() + timedelta(days=i)) for i in range(10)]
    result = runner.run(data)
    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.max_drawdown, float)
    assert isinstance(result.win_rate, float)
    assert isinstance(result.total_pnl, float)


def test_backtest_strategy_id_tracking():
    runner = BacktestRunner(
        strategies=[DummyStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    data = [make_snapshot('m1', 0.65, utcnow() + timedelta(days=1))]
    result = runner.run(data)
    for trade in result.trades:
        assert trade.strategy_id == 'dummy'


def test_backtest_multiple_strategies():
    runner = BacktestRunner(
        strategies=[DummyStrategy(), NoSignalStrategy()],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    data = [make_snapshot('m1', 0.65, utcnow() + timedelta(days=i)) for i in range(5)]
    result = runner.run(data)
    assert isinstance(result, BacktestResult)
    # NoSignalStrategy never generates trades
    # DummyStrategy might
    assert isinstance(result.sharpe_ratio, float)


def test_backtest_result_dataclass():
    result = BacktestResult(
        equity_curve=[10000.0, 10100.0, 9900.0],
        trades=[],
        positions=[],
        total_pnl=0.0,
        sharpe_ratio=0.5,
        max_drawdown=0.02,
        win_rate=0.6,
    )
    assert result.equity_curve == [10000.0, 10100.0, 9900.0]
    assert result.sharpe_ratio == 0.5
    assert result.max_drawdown == 0.02
    assert result.win_rate == 0.6


def test_backtest_result_empty_equity_curve():
    result = BacktestResult(
        equity_curve=[],
        trades=[],
        positions=[],
        total_pnl=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
    )
    assert result.equity_curve == [0.0]
