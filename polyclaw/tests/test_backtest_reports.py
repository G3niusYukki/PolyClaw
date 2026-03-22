"""Tests for performance reporting."""

import json
from datetime import datetime

from polyclaw.backtest.reports import PerformanceReport
from polyclaw.backtest.runner import BacktestResult, TradeRecord


def test_report_generate():
    reporter = PerformanceReport()
    result = BacktestResult(
        equity_curve=[10000.0, 10100.0, 9900.0, 10200.0],
        trades=[],
        positions=[],
        total_pnl=200.0,
        sharpe_ratio=0.8,
        max_drawdown=0.02,
        win_rate=0.5,
    )
    report = reporter.generate(result)
    assert 'summary' in report
    assert 'raw' in report
    assert report['summary']['total_trades'] == 0


def test_report_with_trades():
    reporter = PerformanceReport()
    trades = [
        TradeRecord(
            timestamp=None,
            market_id='m1',
            side='yes',
            entry_price=0.5,
            exit_price=0.6,
            pnl=10.0,
            strategy_id='test',
        ),
        TradeRecord(
            timestamp=None,
            market_id='m2',
            side='yes',
            entry_price=0.5,
            exit_price=0.4,
            pnl=-10.0,
            strategy_id='test',
        ),
    ]
    result = BacktestResult(
        equity_curve=[10000.0, 10010.0, 10000.0, 10010.0],
        trades=trades,
        positions=[],
        total_pnl=10.0,
        sharpe_ratio=0.5,
        max_drawdown=0.01,
        win_rate=0.5,
    )
    report = reporter.generate(result)
    assert report['summary']['total_trades'] == 2
    assert report['summary']['win_rate'] == '50.0%'
    assert report['raw']['win_rate'] == 0.5


def test_report_summary_output():
    reporter = PerformanceReport()
    result = BacktestResult(
        equity_curve=[10000.0, 10100.0],
        trades=[],
        positions=[],
        total_pnl=100.0,
        sharpe_ratio=1.2,
        max_drawdown=0.05,
        win_rate=0.6,
    )
    summary = reporter.summary(result)
    assert 'BACKTEST PERFORMANCE REPORT' in summary
    assert 'Sharpe Ratio' in summary
    assert 'Max Drawdown' in summary
    assert 'Win Rate' in summary


def test_report_to_json():
    reporter = PerformanceReport()
    result = BacktestResult(
        equity_curve=[10000.0, 10200.0],
        trades=[],
        positions=[],
        total_pnl=200.0,
        sharpe_ratio=0.9,
        max_drawdown=0.03,
        win_rate=0.55,
    )
    json_str = reporter.to_json(result)
    data = json.loads(json_str)
    assert 'report' in data
    assert 'equity_curve' in data
    assert data['equity_curve'] == [10000.0, 10200.0]


def test_report_profit_factor_winning_only():
    reporter = PerformanceReport()
    trades = [
        TradeRecord(
            timestamp=None,
            market_id='m1',
            side='yes',
            entry_price=0.5,
            exit_price=0.6,
            pnl=10.0,
            strategy_id='test',
        ),
        TradeRecord(
            timestamp=None,
            market_id='m2',
            side='yes',
            entry_price=0.5,
            exit_price=0.7,
            pnl=20.0,
            strategy_id='test',
        ),
    ]
    result = BacktestResult(
        equity_curve=[10000.0, 10010.0, 10030.0],
        trades=trades,
        positions=[],
        total_pnl=30.0,
        sharpe_ratio=1.0,
        max_drawdown=0.0,
        win_rate=1.0,
    )
    report = reporter.generate(result)
    assert report['summary']['profit_factor'] == 'inf'


def test_report_empty_trades():
    reporter = PerformanceReport()
    result = BacktestResult(
        equity_curve=[10000.0],
        trades=[],
        positions=[],
        total_pnl=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
    )
    report = reporter.generate(result)
    assert report['summary']['total_trades'] == 0
    assert report['summary']['win_rate'] == '0.0%'
    assert report['summary']['profit_factor'] == '0.00'


def test_report_avg_holding_period():
    from datetime import datetime
    reporter = PerformanceReport()
    trades = [
        TradeRecord(
            timestamp=datetime(2025, 1, 1, 12, 0),
            market_id='m1',
            side='yes',
            entry_price=0.5,
            exit_price=0.6,
            pnl=10.0,
            strategy_id='test',
            exit_timestamp=datetime(2025, 1, 1, 18, 0),  # 6 hours
        ),
        TradeRecord(
            timestamp=datetime(2025, 1, 2, 10, 0),
            market_id='m2',
            side='yes',
            entry_price=0.5,
            exit_price=0.4,
            pnl=-5.0,
            strategy_id='test',
            exit_timestamp=datetime(2025, 1, 2, 14, 0),  # 4 hours
        ),
    ]
    result = BacktestResult(
        equity_curve=[10000.0, 10010.0, 10005.0],
        trades=trades,
        positions=[],
        total_pnl=5.0,
        sharpe_ratio=0.3,
        max_drawdown=0.01,
        win_rate=0.5,
    )
    report = reporter.generate(result)
    # Average of 6 and 4 hours = 5 hours
    assert '5.00h' in report['summary']['avg_holding_period_hours']


def test_report_trades_json_serialization():
    reporter = PerformanceReport()
    trades = [
        TradeRecord(
            timestamp=datetime(2025, 1, 1, 12, 0),
            market_id='m1',
            side='yes',
            entry_price=0.5,
            exit_price=0.6,
            pnl=10.0,
            strategy_id='test',
            exit_timestamp=datetime(2025, 1, 1, 18, 0),
            quantity=100.0,
            notional_usd=50.0,
            slippage_pct=0.002,
        ),
    ]
    result = BacktestResult(
        equity_curve=[10000.0, 10010.0],
        trades=trades,
        positions=[],
        total_pnl=10.0,
        sharpe_ratio=0.5,
        max_drawdown=0.01,
        win_rate=1.0,
    )
    json_str = reporter.to_json(result)
    data = json.loads(json_str)
    assert len(data['trades']) == 1
    assert data['trades'][0]['market_id'] == 'm1'
    assert data['trades'][0]['side'] == 'yes'
    assert data['trades'][0]['pnl'] == 10.0
