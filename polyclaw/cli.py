import argparse
import json
from datetime import date, timedelta
from typing import TypedDict

from polyclaw.db import Base, SessionLocal, engine
from polyclaw.services.runner import RunnerService


def main() -> None:
    parser = argparse.ArgumentParser(description='PolyClaw runner')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # tick command
    subparsers.add_parser('tick', help='Run a single analysis tick')

    # backtest command
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest with walk-forward validation')
    backtest_parser.add_argument(
        '--strategy',
        type=str,
        default='event_catalyst',
        help='Strategy ID to backtest (default: event_catalyst)',
    )
    backtest_parser.add_argument(
        '--start-date',
        type=str,
        default=None,
        help='Start date (YYYY-MM-DD). Defaults to 90 days ago.',
    )
    backtest_parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD). Defaults to today.',
    )
    backtest_parser.add_argument(
        '--train-days',
        type=int,
        default=60,
        help='Training period in days for walk-forward (default: 60)',
    )
    backtest_parser.add_argument(
        '--test-days',
        type=int,
        default=30,
        help='Testing period in days for walk-forward (default: 30)',
    )
    backtest_parser.add_argument(
        '--format',
        choices=['summary', 'json', 'detailed'],
        default='summary',
        help='Output format (default: summary)',
    )

    args = parser.parse_args()

    if args.command == 'tick':
        Base.metadata.create_all(bind=engine)
        session = SessionLocal()
        try:
            result = RunnerService().tick(session)
            print(json.dumps(result, indent=2, default=str))
        finally:
            session.close()
    elif args.command == 'backtest':
        run_backtest(args)


def run_backtest(args: argparse.Namespace) -> None:
    """Run the backtest command."""
    from polyclaw.backtest.reports import PerformanceReport
    from polyclaw.backtest.runner import BacktestRunner
    from polyclaw.backtest.walkforward import WalkForwardValidator
    from polyclaw.strategies import get_strategy
    from polyclaw.timeutils import utcnow

    # Parse dates
    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = (utcnow() - timedelta(days=90)).date()

    if args.end_date:
        end_date = date.fromisoformat(args.end_date)
    else:
        end_date = utcnow().date()

    # Get strategy
    try:
        strategy = get_strategy(args.strategy)
    except ValueError as e:
        print(f'Error: {e}')
        return

    # Generate sample market data for the date range
    market_data = _generate_sample_history(start_date, end_date)

    if not market_data:
        print('No market data available for the specified date range.')
        return

    # Run walk-forward validation
    if not strategy:
        print(f'Error: Strategy {args.strategy!r} not found in registry.')
        return
    validator = WalkForwardValidator(
        strategy=strategy,
        train_days=args.train_days,
        test_days=args.test_days,
    )
    wf_result = validator.run(market_data)

    # Run a single full backtest for the summary
    runner = BacktestRunner(
        strategies=[strategy],
        start_date=start_date,
        end_date=end_date,
    )
    result = runner.run(market_data)

    reporter = PerformanceReport()

    if args.format == 'json':
        output = reporter.to_json(result)
        wf_data = {
            'walk_forward': {
                'total_windows': wf_result.total_windows,
                'avg_sharpe': wf_result.avg_sharpe,
                'avg_max_dd': wf_result.avg_max_dd,
                'avg_win_rate': wf_result.avg_win_rate,
                'pass_gate': wf_result.pass_gate,
                'windows': [
                    {
                        'window': w.window_index,
                        'sharpe': w.sharpe_ratio,
                        'max_dd': w.max_drawdown,
                        'win_rate': w.win_rate,
                        'trades': w.total_trades,
                    }
                    for w in wf_result.windows
                ],
            }
        }
        data = json.loads(output)
        data['walk_forward'] = wf_data['walk_forward']
        print(json.dumps(data, indent=2))
    elif args.format == 'detailed':
        print(reporter.summary(result))
        print()
        print(f"Walk-Forward Validation ({wf_result.total_windows} windows):")
        print(f"  Avg Sharpe     : {wf_result.avg_sharpe:.4f}")
        print(f"  Avg Max DD     : {wf_result.avg_max_dd:.4f}")
        print(f"  Avg Win Rate   : {wf_result.avg_win_rate:.4f}")
        print(f"  Pass Gate      : {'PASS' if wf_result.pass_gate else 'FAIL'}")
        print()
        if wf_result.windows:
            print("Per-window breakdown:")
            for w in wf_result.windows:
                print(
                    f"  Window {w.window_index}: "
                    f"Sharpe={w.sharpe_ratio:.4f} "
                    f"DD={w.max_drawdown:.4f} "
                    f"WR={w.win_rate:.4f} "
                    f"Trades={w.total_trades}"
                )
    else:
        print(reporter.summary(result))
        print()
        print(f"Walk-Forward ({wf_result.total_windows} windows, train={args.train_days}d, test={args.test_days}d):")
        print(f"  Avg Sharpe     : {wf_result.avg_sharpe:.4f}")
        print(f"  Avg Max DD     : {wf_result.avg_max_dd:.4f}")
        print(f"  Avg Win Rate   : {wf_result.avg_win_rate:.4f}")
        print(f"  Pass Gate      : {'PASS' if wf_result.pass_gate else 'FAIL'}")


def _generate_sample_history(start_date: date, end_date: date) -> list:
    """Generate synthetic historical market data for the date range."""
    from polyclaw.domain import MarketSnapshot
    from polyclaw.timeutils import utcnow

    data: list[MarketSnapshot] = []
    current = start_date
    day = timedelta(days=1)

    class MarketConfig(TypedDict):
        market_id: str
        title: str
        description: str
        yes_price: float
        no_price: float
        spread_bps: int
        liquidity_usd: float
        volume_24h_usd: float
        category: str
        event_key: str
        resolution_days_offset: int

    market_configs: list[MarketConfig] = [
        {
            'market_id': 'pm-us-election-demo',
            'title': 'Will candidate A win and be elected?',
            'description': 'Deterministic demo market.',
            'yes_price': 0.25,
            'no_price': 0.77,
            'spread_bps': 180,
            'liquidity_usd': 25000,
            'volume_24h_usd': 7000,
            'category': 'politics',
            'event_key': 'demo-election-2026',
            'resolution_days_offset': 15,
        },
        {
            'market_id': 'pm-fed-cut-demo',
            'title': 'Will the Fed approve rate cuts by next meeting?',
            'description': 'Deterministic demo market.',
            'yes_price': 0.20,
            'no_price': 0.82,
            'spread_bps': 220,
            'liquidity_usd': 18000,
            'volume_24h_usd': 4500,
            'category': 'macro',
            'event_key': 'fed-cut-next-meeting-demo',
            'resolution_days_offset': 12,
        },
        {
            'market_id': 'pm-inflation-demo',
            'title': 'Will CPI come in below expectations?',
            'description': 'Macro demo market.',
            'yes_price': 0.22,
            'no_price': 0.80,
            'spread_bps': 160,
            'liquidity_usd': 15000,
            'volume_24h_usd': 3500,
            'category': 'macro',
            'event_key': 'inflation-cpi-demo',
            'resolution_days_offset': 8,
        },
        {
            'market_id': 'pm-election-win',
            'title': 'Will candidate X win and be confirmed?',
            'description': 'Election outcome market.',
            'yes_price': 0.18,
            'no_price': 0.84,
            'spread_bps': 140,
            'liquidity_usd': 30000,
            'volume_24h_usd': 9000,
            'category': 'politics',
            'event_key': 'election-2026',
            'resolution_days_offset': 20,
        },
        {
            'market_id': 'pm-fed-rate-cut',
            'title': 'Will the Fed confirm a rate cut at the next FOMC meeting?',
            'description': 'FOMC rate decision.',
            'yes_price': 0.15,
            'no_price': 0.87,
            'spread_bps': 120,
            'liquidity_usd': 22000,
            'volume_24h_usd': 6000,
            'category': 'macro',
            'event_key': 'fomc-rate-decision',
            'resolution_days_offset': 10,
        },
    ]

    import random
    random.seed(42)

    while current <= end_date:
        for config in market_configs:
            # Add some price noise to simulate market movement
            noise = random.uniform(-0.03, 0.03)
            yes_price = max(0.05, min(0.95, config['yes_price'] + noise))
            no_price = 1 - yes_price + random.uniform(-0.01, 0.01)
            no_price = max(0.05, min(0.95, no_price))

            resolution_offset = config.get('resolution_days_offset', 10)
            snapshot_fetch_time = utcnow().replace(
                year=current.year,
                month=current.month,
                day=current.day,
                hour=12,
                minute=0,
                second=0,
                microsecond=0,
            )
            snapshot = MarketSnapshot(
                market_id=config['market_id'],
                title=config['title'],
                description=config['description'],
                yes_price=round(yes_price, 4),
                no_price=round(no_price, 4),
                spread_bps=config['spread_bps'] + random.randint(-20, 20),
                liquidity_usd=config['liquidity_usd'] + random.uniform(-2000, 2000),
                volume_24h_usd=config['volume_24h_usd'] + random.uniform(-1000, 1000),
                category=config['category'],
                event_key=config['event_key'],
                closes_at=snapshot_fetch_time + timedelta(days=resolution_offset),
                fetched_at=snapshot_fetch_time,
            )
            data.append(snapshot)

        current += day

    return data


if __name__ == '__main__':
    main()
