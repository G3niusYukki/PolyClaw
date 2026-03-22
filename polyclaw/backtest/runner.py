"""Backtest runner for strategy simulation."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy


@dataclass
class TradeRecord:
    """Record of a single backtest trade."""
    timestamp: datetime
    market_id: str
    side: str
    entry_price: float
    exit_price: float | None
    pnl: float
    strategy_id: str
    exit_timestamp: datetime | None = None
    quantity: float = 1.0
    notional_usd: float = 0.0
    slippage_pct: float = 0.0
    explanation: str = ''


@dataclass
class PositionRecord:
    """Record of an open position during backtest."""
    market_id: str
    side: str
    entry_price: float
    quantity: float
    notional_usd: float
    entry_timestamp: datetime
    strategy_id: str
    is_open: bool = True


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    equity_curve: list[float]
    trades: list[TradeRecord]
    positions: list[PositionRecord]
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    timestamps: list[datetime] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.equity_curve:
            self.equity_curve = [0.0]
        if not self.timestamps:
            self.timestamps = []


class BacktestRunner:
    """Event-driven backtest simulator for strategies.

    Iterates through market snapshots chronologically, computing features,
    generating signals, applying risk checks, and recording trades.
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        start_date: date,
        end_date: date,
        initial_capital: float = 10_000.0,
    ) -> None:
        self.strategies = strategies
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital

        self._equity: list[float] = [initial_capital]
        self._timestamps: list[datetime] = []
        self._trades: list[TradeRecord] = []
        self._positions: list[PositionRecord] = []
        self._closed_trades: list[TradeRecord] = []
        self._last_trade_count: int = 0

    def run(self, market_data: list[MarketSnapshot]) -> BacktestResult:
        """Run the backtest over the given market data chronologically.

        Args:
            market_data: Chronologically sorted list of market snapshots.

        Returns:
            BacktestResult with equity curve, trades, positions, and metrics.
        """
        if not market_data:
            return BacktestResult(
                equity_curve=[self.initial_capital],
                trades=[],
                positions=[],
                total_pnl=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                timestamps=[],
            )

        # Sort by fetch time just in case
        sorted_data = sorted(market_data, key=lambda m: m.fetched_at)

        # Group snapshots by market_id for easier lookup
        market_history: dict[str, list[MarketSnapshot]] = {}
        for snapshot in sorted_data:
            if snapshot.market_id not in market_history:
                market_history[snapshot.market_id] = []
            market_history[snapshot.market_id].append(snapshot)

        # Track all unique timestamps in order
        all_timestamps: list[datetime] = []
        seen_times: set[datetime] = set()
        for snapshot in sorted_data:
            if snapshot.fetched_at not in seen_times:
                all_timestamps.append(snapshot.fetched_at)
                seen_times.add(snapshot.fetched_at)

        # Event-driven simulation
        for ts in all_timestamps:
            current_snapshot: dict[str, MarketSnapshot] = {}
            for market_id, snapshots in market_history.items():
                for snap in snapshots:
                    if snap.fetched_at <= ts:
                        current_snapshot[market_id] = snap

            # Process signals from all strategies
            for strategy in self.strategies:
                for market_id, market in current_snapshot.items():
                    # Skip if we already have an open position for this market
                    existing = [p for p in self._positions if p.market_id == market_id and p.is_open]
                    if existing:
                        self._maybe_close_position(market, strategy.strategy_id)
                        continue

                    # Compute features and generate signal
                    features = strategy.compute_features(market)
                    signal = strategy.generate_signals(market, features)

                    if signal is None:
                        continue

                    # Apply risk checks
                    if not self._risk_check(market, signal):
                        continue

                    # Compute stake
                    stake = min(
                        signal.edge_bps / 100.0 + 10.0,
                        settings.max_position_usd,
                    )

                    # Open position
                    self._open_position(market, signal, strategy.strategy_id, stake, ts)

                # Check if any open positions can be closed
                for pos in list(self._positions):
                    if pos.is_open and pos.market_id in current_snapshot:
                        self._maybe_close_position(current_snapshot[pos.market_id], strategy.strategy_id)

            # Record equity at this timestamp
            self._update_equity(ts)

        # Close all remaining positions at the last known price
        if sorted_data:
            last_ts = sorted_data[-1].fetched_at
            for pos in self._positions:
                if pos.is_open:
                    self._close_position_at_price(pos, 0.5, last_ts)

        self._update_equity(all_timestamps[-1] if all_timestamps else datetime.now())

        return BacktestResult(
            equity_curve=self._equity.copy(),
            trades=self._closed_trades.copy(),
            positions=self._positions.copy(),
            total_pnl=round(self._equity[-1] - self.initial_capital, 2),
            sharpe_ratio=round(self._compute_sharpe(), 4),
            max_drawdown=round(self._compute_max_drawdown(), 4),
            win_rate=round(self._compute_win_rate(), 4),
            timestamps=self._timestamps.copy(),
        )

    def _open_position(
        self,
        market: MarketSnapshot,
        signal,
        strategy_id: str,
        stake: float,
        ts: datetime,
    ) -> None:
        """Open a position based on a signal."""
        if signal.side.value == 'yes':
            price = market.yes_price
        else:
            price = market.no_price

        quantity = stake / price if price > 0 else 0

        position = PositionRecord(
            market_id=market.market_id,
            side=signal.side.value,
            entry_price=price,
            quantity=quantity,
            notional_usd=stake,
            entry_timestamp=ts,
            strategy_id=strategy_id,
            is_open=True,
        )
        self._positions.append(position)

    def _maybe_close_position(self, market: MarketSnapshot, strategy_id: str) -> None:
        """Close a position if the exit signal is strong enough."""
        current_ts = market.fetched_at
        for pos in list(self._positions):
            if pos.market_id != market.market_id or not pos.is_open:
                continue

            # Close if market has reached its resolution date
            if market.closes_at and current_ts >= market.closes_at:
                self._close_position_at_price(pos, market.yes_price, current_ts)
                continue

            # Close if max holding period exceeded (7 days)
            max_holding = timedelta(days=7)
            if current_ts - pos.entry_timestamp >= max_holding:
                if pos.side == 'yes':
                    exit_price = market.yes_price
                else:
                    exit_price = market.no_price
                self._close_position_at_price(pos, exit_price, current_ts)
                continue

            # Simple heuristic: close if price moved significantly
            if pos.side == 'yes':
                current_price = market.yes_price
            else:
                current_price = market.no_price

            price_delta = abs(current_price - pos.entry_price)
            # Close if price moved more than 5%
            if price_delta > 0.05:
                self._close_position_at_price(pos, current_price, current_ts)

    def _close_position_at_price(
        self,
        pos: PositionRecord,
        exit_price: float,
        exit_ts: datetime,
    ) -> None:
        """Close a position at the given price."""
        if not pos.is_open:
            return

        pos.is_open = False

        if pos.side == 'yes':
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        trade = TradeRecord(
            timestamp=pos.entry_timestamp,
            market_id=pos.market_id,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl=round(pnl, 4),
            strategy_id=pos.strategy_id,
            exit_timestamp=exit_ts,
            quantity=pos.quantity,
            notional_usd=pos.notional_usd,
            slippage_pct=0.0,
        )
        self._closed_trades.append(trade)
        self._trades.append(trade)

    def _risk_check(self, market: MarketSnapshot, signal) -> bool:
        """Apply basic risk checks before opening a position."""
        if market.spread_bps > settings.max_spread_bps:
            return False
        if market.liquidity_usd < settings.min_liquidity_usd:
            return False
        if signal.confidence < settings.min_confidence:
            return False
        if signal.edge_bps < settings.min_edge_bps:
            return False

        # Check total exposure
        open_notional = sum(p.notional_usd for p in self._positions if p.is_open)
        stake = min(signal.edge_bps / 100.0 + 10.0, settings.max_position_usd)
        if open_notional + stake > settings.max_total_exposure_usd:
            return False

        return True

    def _update_equity(self, ts: datetime) -> None:
        """Update equity curve, adding PnL from newly closed trades."""
        current_equity = self._equity[-1] if self._equity else self.initial_capital

        # Add PnL from any newly closed trades since last update
        new_trades = self._closed_trades[self._last_trade_count:]
        for trade in new_trades:
            current_equity += trade.pnl
        self._last_trade_count = len(self._closed_trades)

        self._equity.append(current_equity)
        self._timestamps.append(ts)

    def _compute_sharpe(self) -> float:
        """Compute annualized Sharpe ratio from equity curve."""
        if len(self._equity) < 3:
            return 0.0

        returns: list[float] = []
        for i in range(1, len(self._equity)):
            prev = self._equity[i - 1]
            curr = self._equity[i]
            if prev > 0:
                ret = (curr - prev) / prev
                returns.append(ret)

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / max(len(returns) - 1, 1)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return 0.0

        # Annualize (assuming daily periods; ~252 trading days)
        sharpe = (mean_ret / std_dev) * (252 ** 0.5)
        return sharpe

    def _compute_max_drawdown(self) -> float:
        """Compute maximum drawdown from equity curve."""
        if not self._equity:
            return 0.0

        peak = self._equity[0]
        max_dd = 0.0

        for equity in self._equity:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _compute_win_rate(self) -> float:
        """Compute win rate from closed trades."""
        if not self._closed_trades:
            return 0.0

        wins = sum(1 for t in self._closed_trades if t.pnl > 0)
        return wins / len(self._closed_trades)
