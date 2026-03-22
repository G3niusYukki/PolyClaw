"""Performance reporting for backtest results."""

import json
from dataclasses import dataclass

from polyclaw.backtest.runner import BacktestResult


@dataclass
class PerformanceMetrics:
    """Structured performance metrics from a backtest."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_trade_pnl: float
    sharpe_ratio: float
    sharpe_ratio_annualized: float
    max_drawdown: float
    max_drawdown_pct: float
    profit_factor: float
    avg_holding_period_hours: float | None
    equity_final: float
    equity_peak: float


class PerformanceReport:
    """Generate performance reports from backtest results."""

    def generate(self, result: BacktestResult) -> dict:
        """Generate a full performance report as a dictionary.

        Args:
            result: The BacktestResult to report on.

        Returns:
            Dictionary with all metrics.
        """
        trades = result.trades
        n = len(trades)

        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl < 0]

        total_wins = sum(t.pnl for t in winning)
        total_loss = abs(sum(t.pnl for t in losing))

        avg_pnl = sum(t.pnl for t in trades) / n if n > 0 else 0.0

        # Compute average holding period
        avg_holding = self._avg_holding_period(trades)

        equity_final = result.equity_curve[-1] if result.equity_curve else 0.0
        equity_peak = max(result.equity_curve) if result.equity_curve else 0.0

        metrics = PerformanceMetrics(
            total_trades=n,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=result.win_rate,
            total_pnl=result.total_pnl,
            avg_trade_pnl=round(avg_pnl, 4),
            sharpe_ratio=result.sharpe_ratio,
            sharpe_ratio_annualized=round(result.sharpe_ratio * (252 ** 0.5), 4),
            max_drawdown=round(result.max_drawdown * equity_peak, 2) if equity_peak > 0 else 0.0,
            max_drawdown_pct=round(result.max_drawdown * 100, 2),
            profit_factor=round(total_wins / total_loss, 4) if total_loss > 0 else float('inf') if total_wins > 0 else 0.0,
            avg_holding_period_hours=avg_holding,
            equity_final=round(equity_final, 2),
            equity_peak=round(equity_peak, 2),
        )

        return {
            'summary': {
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'win_rate': f"{metrics.win_rate * 100:.1f}%",
                'total_pnl': f"${metrics.total_pnl:.2f}",
                'avg_trade_pnl': f"${metrics.avg_trade_pnl:.4f}",
                'sharpe_ratio': f"{metrics.sharpe_ratio:.4f}",
                'sharpe_ratio_annualized': f"{metrics.sharpe_ratio_annualized:.4f}",
                'max_drawdown': f"${metrics.max_drawdown:.2f}",
                'max_drawdown_pct': f"{metrics.max_drawdown_pct:.2f}%",
                'profit_factor': f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float('inf') else 'inf',
                'avg_holding_period_hours': f"{metrics.avg_holding_period_hours:.2f}h" if metrics.avg_holding_period_hours else 'N/A',
                'equity_final': f"${metrics.equity_final:.2f}",
                'equity_peak': f"${metrics.equity_peak:.2f}",
            },
            'raw': {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'total_pnl': metrics.total_pnl,
                'avg_trade_pnl': metrics.avg_trade_pnl,
                'sharpe_ratio': metrics.sharpe_ratio,
                'sharpe_ratio_annualized': metrics.sharpe_ratio_annualized,
                'max_drawdown': metrics.max_drawdown,
                'max_drawdown_pct': metrics.max_drawdown_pct,
                'profit_factor': metrics.profit_factor,
                'avg_holding_period_hours': metrics.avg_holding_period_hours,
                'equity_final': metrics.equity_final,
                'equity_peak': metrics.equity_peak,
            },
        }

    def summary(self, result: BacktestResult) -> str:
        """Generate a console-friendly summary string.

        Args:
            result: The BacktestResult to summarize.

        Returns:
            Formatted string suitable for console output.
        """
        report = self.generate(result)
        s = report['summary']

        lines = [
            '',
            '=' * 50,
            '  BACKTEST PERFORMANCE REPORT',
            '=' * 50,
            '',
            f"  Total Trades       : {s['total_trades']}",
            f"  Winning Trades     : {s['winning_trades']}",
            f"  Losing Trades      : {s['losing_trades']}",
            f"  Win Rate           : {s['win_rate']}",
            '',
            f"  Total PnL          : {s['total_pnl']}",
            f"  Avg Trade PnL      : {s['avg_trade_pnl']}",
            f"  Profit Factor      : {s['profit_factor']}",
            '',
            f"  Sharpe Ratio       : {s['sharpe_ratio']}",
            f"  Sharpe (Annual)    : {s['sharpe_ratio_annualized']}",
            f"  Max Drawdown       : {s['max_drawdown']} ({s['max_drawdown_pct']})",
            '',
            f"  Avg Hold Period    : {s['avg_holding_period_hours']}",
            '',
            f"  Equity (Final)     : {s['equity_final']}",
            f"  Equity (Peak)      : {s['equity_peak']}",
            '',
            '=' * 50,
        ]
        return '\n'.join(lines)

    def to_json(self, result: BacktestResult) -> str:
        """Serialize a backtest result to JSON.

        Args:
            result: The BacktestResult to serialize.

        Returns:
            JSON string of the full report.
        """
        trades_data = []
        for t in result.trades:
            trades_data.append({
                'timestamp': t.timestamp.isoformat() if t.timestamp else None,
                'market_id': t.market_id,
                'side': t.side,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'pnl': t.pnl,
                'strategy_id': t.strategy_id,
                'exit_timestamp': t.exit_timestamp.isoformat() if t.exit_timestamp else None,
                'quantity': t.quantity,
                'notional_usd': t.notional_usd,
                'slippage_pct': t.slippage_pct,
            })

        report = self.generate(result)

        return json.dumps(
            {
                'report': report,
                'trades': trades_data,
                'equity_curve': [
                    round(e, 4) for e in result.equity_curve
                ],
            },
            indent=2,
        )

    def _avg_holding_period(self, trades: list) -> float | None:
        """Compute average holding period in hours from trade records."""
        periods: list[float] = []
        for t in trades:
            if t.timestamp and t.exit_timestamp:
                delta = t.exit_timestamp - t.timestamp
                periods.append(delta.total_seconds() / 3600)

        if not periods:
            return None

        return round(sum(periods) / len(periods), 2)
