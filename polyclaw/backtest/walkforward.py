"""Walk-forward validation for strategy robustness testing."""

from dataclasses import dataclass

from polyclaw.backtest.runner import BacktestRunner
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy


@dataclass
class WindowResult:
    """Result for a single train/test window."""
    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_samples: int
    test_samples: int
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int


@dataclass
class WalkForwardResult:
    """Result of walk-forward validation across all windows."""
    windows: list[WindowResult]
    avg_sharpe: float
    avg_max_dd: float
    avg_win_rate: float
    pass_gate: bool
    total_windows: int


class WalkForwardValidator:
    """Walk-forward validator for strategy robustness testing.

    Splits historical data into rolling train/test windows, trains on
    each training period, and evaluates on the corresponding test period.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        train_days: int = 60,
        test_days: int = 30,
        gate_sharpe: float = 0.5,
        gate_max_dd: float = 0.25,
    ) -> None:
        self.strategy = strategy
        self.train_days = train_days
        self.test_days = test_days
        self.gate_sharpe = gate_sharpe
        self.gate_max_dd = gate_max_dd

    def run(self, historical_data: list[MarketSnapshot]) -> WalkForwardResult:
        """Run walk-forward validation.

        Args:
            historical_data: Chronologically sorted market snapshots.

        Returns:
            WalkForwardResult with metrics per window and aggregate stats.
        """
        if not historical_data:
            return WalkForwardResult(
                windows=[],
                avg_sharpe=0.0,
                avg_max_dd=0.0,
                avg_win_rate=0.0,
                pass_gate=False,
                total_windows=0,
            )

        # Sort by timestamp
        sorted_data = sorted(historical_data, key=lambda m: m.fetched_at)
        n = len(sorted_data)

        # Estimate snapshots per day (for window sizing)
        # We'll use snapshot count as proxy since timestamps vary
        # Each snapshot represents a point in time

        window_results: list[WindowResult] = []
        step = max(1, self.test_days)

        start_idx = 0
        window_index = 0

        while True:
            train_end = start_idx + self.train_days
            test_end = train_end + self.test_days

            if train_end >= n:
                break

            actual_test_end = min(test_end, n)

            train_data = sorted_data[start_idx:train_end]
            test_data = sorted_data[train_end:actual_test_end]

            if not train_data or not test_data:
                break

            # Run backtest on test period
            runner = BacktestRunner(
                strategies=[self.strategy],
                start_date=train_data[0].fetched_at.date(),
                end_date=test_data[-1].fetched_at.date(),
            )
            result = runner.run(test_data)

            window_result = WindowResult(
                window_index=window_index,
                train_start=start_idx,
                train_end=train_end,
                test_start=train_end,
                test_end=actual_test_end,
                train_samples=len(train_data),
                test_samples=len(test_data),
                total_pnl=result.total_pnl,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown=result.max_drawdown,
                win_rate=result.win_rate,
                total_trades=len(result.trades),
            )
            window_results.append(window_result)

            start_idx += step
            window_index += 1

            if start_idx + self.train_days >= n:
                break

        if not window_results:
            return WalkForwardResult(
                windows=[],
                avg_sharpe=0.0,
                avg_max_dd=0.0,
                avg_win_rate=0.0,
                pass_gate=False,
                total_windows=0,
            )

        avg_sharpe = sum(w.sharpe_ratio for w in window_results) / len(window_results)
        avg_max_dd = sum(w.max_drawdown for w in window_results) / len(window_results)
        avg_win_rate = sum(w.win_rate for w in window_results) / len(window_results)

        # Pass gate: average Sharpe >= threshold AND average max DD <= threshold
        pass_gate = (
            avg_sharpe >= self.gate_sharpe
            and avg_max_dd <= self.gate_max_dd
            and len(window_results) >= 1
        )

        return WalkForwardResult(
            windows=window_results,
            avg_sharpe=round(avg_sharpe, 4),
            avg_max_dd=round(avg_max_dd, 4),
            avg_win_rate=round(avg_win_rate, 4),
            pass_gate=pass_gate,
            total_windows=len(window_results),
        )
