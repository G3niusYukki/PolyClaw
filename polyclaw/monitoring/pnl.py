"""PnL Attribution Reports — daily PnL breakdown, strategy attribution, and equity curves."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from polyclaw.models import Position, ShadowResult
from polyclaw.monitoring.channels import ChannelResponse, TelegramChannel
from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class PnLSummary:
    """PnL summary for a given time period."""
    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    sharpe_ratio: float | None


@dataclass
class EquityPoint:
    """Single point on an equity curve."""
    date: datetime
    equity_usd: float
    drawdown_pct: float
    pnl_day: float


class PnLReporter:
    """
    Generates PnL attribution reports from trading data.

    Computes daily PnL breakdown by strategy and market, calculates
    equity curves with drawdown, and derives performance metrics.
    """

    def daily_pnl(self, session: 'Session', date: datetime | None = None) -> dict:
        """
        Calculate daily PnL breakdown.

        Args:
            session: SQLAlchemy session
            date: Target date (defaults to today)

        Returns:
            dict with:
              - by_strategy: {strategy_id: pnl_usd}
              - by_market: {market_id: pnl_usd}
              - by_side: {'yes': pnl_usd, 'no': pnl_usd}
              - total_pnl: float
              - trade_count: int
        """
        target_date = (date or utcnow()).date()

        # Get resolved shadow results for the target date
        start = datetime.combine(target_date, datetime.min.time())
        end = start + timedelta(days=1)

        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= start)
            .where(ShadowResult.resolved_at < end)
            .where(ShadowResult.actual_outcome != '')
        )
        results = session.scalars(stmt).all()

        by_strategy: dict[str, float] = {}
        by_market: dict[str, float] = {}
        by_side: dict[str, float] = {'yes': 0.0, 'no': 0.0}
        total_pnl = 0.0

        for r in results:
            pnl = r.pnl
            total_pnl += pnl
            by_strategy[r.strategy_id] = by_strategy.get(r.strategy_id, 0.0) + pnl
            by_market[r.market_id] = by_market.get(r.market_id, 0.0) + pnl

            # Determine side from prediction
            if r.predicted_side in ('yes', 'no'):
                by_side[r.predicted_side] = by_side.get(r.predicted_side, 0.0) + pnl

        return {
            'date': target_date.isoformat(),
            'by_strategy': by_strategy,
            'by_market': by_market,
            'by_side': by_side,
            'total_pnl': round(total_pnl, 4),
            'trade_count': len(results),
        }

    def attribution(self, session: 'Session', start_date: datetime, end_date: datetime) -> dict:
        """
        Calculate strategy attribution over a date range.

        Args:
            session: SQLAlchemy session
            start_date: Start of the attribution period
            end_date: End of the attribution period

        Returns:
            dict with:
              - period: {'start': str, 'end': str}
              - strategies: {strategy_id: {'pnl': float, 'trades': int, 'wins': int, 'win_rate': float}}
              - total_pnl: float
        """
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= start_date)
            .where(ShadowResult.resolved_at < end_date)
            .where(ShadowResult.actual_outcome != '')
        )
        results = session.scalars(stmt).all()

        strategies: dict[str, dict] = {}
        total_pnl = 0.0

        for r in results:
            total_pnl += r.pnl
            if r.strategy_id not in strategies:
                strategies[r.strategy_id] = {'pnl': 0.0, 'trades': 0, 'wins': 0}
            strategies[r.strategy_id]['pnl'] += r.pnl
            strategies[r.strategy_id]['trades'] += 1
            if r.accuracy:
                strategies[r.strategy_id]['wins'] += 1

        # Compute win rates
        for sid, data in strategies.items():
            data['win_rate'] = round(data['wins'] / data['trades'], 4) if data['trades'] > 0 else 0.0
            data['pnl'] = round(data['pnl'], 4)

        return {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
            },
            'strategies': strategies,
            'total_pnl': round(total_pnl, 4),
        }

    def equity_curve(self, session: 'Session', days: int = 90) -> list[dict]:
        """
        Generate a daily equity curve with drawdown over the specified window.

        Args:
            session: SQLAlchemy session
            days: Number of days to look back (default 90)

        Returns:
            List of equity points with date, equity_usd, drawdown_pct, pnl_day
        """
        cutoff = utcnow() - timedelta(days=days)
        peak = 0.0
        equity_points: list[dict] = []

        # Group resolved results by day
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= cutoff)
            .where(ShadowResult.actual_outcome != '')
            .order_by(ShadowResult.resolved_at)
        )
        results = session.scalars(stmt).all()

        # Aggregate PnL by day
        daily_pnl: dict[str, float] = {}
        for r in results:
            if r.resolved_at is None:
                continue
            day_key = r.resolved_at.strftime('%Y-%m-%d')
            daily_pnl[day_key] = daily_pnl.get(day_key, 0.0) + r.pnl

        # Start with base equity
        current_equity = 0.0
        for day_key in sorted(daily_pnl.keys()):
            current_equity += daily_pnl[day_key]
            peak = max(peak, current_equity)
            drawdown = ((peak - current_equity) / max(peak, 1.0)) * 100.0 if peak > 0 else 0.0
            equity_points.append({
                'date': day_key,
                'equity_usd': round(current_equity, 4),
                'drawdown_pct': round(drawdown, 4),
                'pnl_day': round(daily_pnl[day_key], 4),
            })

        return equity_points


@dataclass
class DailyReport:
    """Aggregated daily trading report."""
    date: str
    pnl_summary: PnLSummary
    top_positions: list[dict]
    trade_count: int
    win_rate: float
    sharpe_ratio: float | None
    unrealized_pnl: float


class DailyReportGenerator:
    """
    Generates and sends daily PnL reports.

    Aggregates PnL data, computes metrics, and optionally sends
    summaries via Telegram.
    """

    def __init__(self, pnl_reporter: PnLReporter | None = None):
        self.pnl_reporter = pnl_reporter or PnLReporter()
        self._telegram: TelegramChannel | None = None

    @property
    def telegram(self) -> TelegramChannel:
        if self._telegram is None:
            self._telegram = TelegramChannel()
        return self._telegram

    def generate(self, session: 'Session', date: datetime | None = None) -> DailyReport:
        """
        Generate a comprehensive daily report.

        Args:
            session: SQLAlchemy session
            date: Target date (defaults to today)

        Returns:
            DailyReport with PnL summary, trade counts, metrics, and positions
        """
        target_date = date or utcnow()
        target_date_only = target_date.date()

        # Get daily PnL data
        daily = self.pnl_reporter.daily_pnl(session, target_date)

        # Get top positions by notional
        pos_stmt = (
            select(Position)
            .where(Position.is_open.is_(True))
            .order_by(Position.notional_usd.desc())
            .limit(5)
        )
        top_positions = session.scalars(pos_stmt).all()
        top_positions_data = [
            {
                'market_id': p.market_id,
                'side': p.side,
                'notional_usd': p.notional_usd,
                'avg_price': p.avg_price,
            }
            for p in top_positions
        ]

        # Calculate unrealized PnL from open positions
        unrealized_pnl = 0.0
        for pos in top_positions:
            # Approximate unrealized PnL based on position and current price
            if pos.side == 'yes':
                unrealized_pnl += pos.notional_usd * (1.0 - pos.avg_price)
            else:
                unrealized_pnl += pos.notional_usd * (0.0 + pos.avg_price)

        # Get results for the day to compute summary metrics
        start = datetime.combine(target_date_only, datetime.min.time())
        end = start + timedelta(days=1)
        stmt = (
            select(ShadowResult)
            .where(ShadowResult.resolved_at >= start)
            .where(ShadowResult.resolved_at < end)
            .where(ShadowResult.actual_outcome != '')
        )
        results = list(session.scalars(stmt).all())

        total_pnl = sum(r.pnl for r in results)
        win_count = sum(1 for r in results if r.accuracy)
        loss_count = len(results) - win_count
        win_rate = win_count / len(results) if results else 0.0

        # Compute Sharpe ratio (simplified: pnl / sqrt(n) * sqrt(252))
        sharpe = None
        if results and len(results) > 1:
            pnls = [r.pnl for r in results]
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
            std_dev = max(variance ** 0.5, 1e-9)
            sharpe = round(mean_pnl / std_dev * (252 ** 0.5), 4)

        pnl_summary = PnLSummary(
            total_pnl=round(total_pnl, 4),
            trade_count=len(results),
            win_count=win_count,
            loss_count=loss_count,
            win_rate=round(win_rate, 4),
            sharpe_ratio=sharpe,
        )

        return DailyReport(
            date=target_date_only.isoformat(),
            pnl_summary=pnl_summary,
            top_positions=top_positions_data,
            trade_count=len(results),
            win_rate=round(win_rate, 4),
            sharpe_ratio=sharpe,
            unrealized_pnl=round(unrealized_pnl, 4),
        )

    def send_telegram(self, report: DailyReport) -> ChannelResponse:
        """
        Send a daily report summary via Telegram.

        Args:
            report: The DailyReport to send

        Returns:
            ChannelResponse with send status
        """
        pnl = report.pnl_summary
        emoji = '\u2705' if pnl.total_pnl >= 0 else '\u274c'
        sign = '+' if pnl.total_pnl >= 0 else ''

        title = f'Daily Report {report.date}'
        body = (
            f'{emoji} <b>PolyClaw Daily Report</b>\n'
            f'<b>Date:</b> {report.date}\n\n'
            f'<b>PnL:</b> {sign}${pnl.total_pnl:.2f}\n'
            f'<b>Trades:</b> {pnl.trade_count} ({pnl.win_count}W / {pnl.loss_count}L)\n'
            f'<b>Win Rate:</b> {pnl.win_rate:.1%}\n'
            f'<b>Unrealized PnL:</b> ${report.unrealized_pnl:.2f}\n'
        )

        if pnl.sharpe_ratio is not None:
            body += f'<b>Sharpe:</b> {pnl.sharpe_ratio:.2f}\n'

        body += f'\n<b>Top Positions ({len(report.top_positions)})</b>\n'
        for pos in report.top_positions[:3]:
            body += f'  {pos["side"].upper()} {pos["market_id"][:16]}... ${pos["notional_usd"]:.2f}\n'

        return self.telegram.send(
            title=title,
            message=body,
            severity='INFO',
            metadata={
                'date': report.date,
                'pnl': str(pnl.total_pnl),
                'trade_count': str(pnl.trade_count),
                'win_rate': str(pnl.win_rate),
            },
        )
