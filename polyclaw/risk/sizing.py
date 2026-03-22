from dataclasses import dataclass


@dataclass
class KellyResult:
    """Result of Kelly position sizing calculation."""
    kelly_fraction: float  # Full Kelly fraction (may be > 1.0 or negative)
    fractional_kelly: float  # Conservative fraction (e.g. quarter-Kelly)
    suggested_stake: float  # Dollar amount in USD
    cap_reason: str | None  # Explanation if cap was applied, None otherwise


class KellyPositionSizer:
    """
    Position sizing using the Kelly criterion with fractional Kelly
    for conservative risk management.
    """

    def calculate_kelly_fraction(
        self, win_rate: float, avg_win: float, avg_loss: float
    ) -> float:
        """
        Calculate the full Kelly fraction.

        Formula: f* = (bp - q) / b
          where b = avg_win / avg_loss (win/loss ratio)
                p = win_rate (probability of win)
                q = 1 - p (probability of loss)

        Returns the raw Kelly fraction (can be negative or > 1.0 in edge cases).
        """
        if avg_loss == 0:
            # Cannot compute Kelly with zero loss
            return 0.0
        if win_rate < 0 or win_rate > 1.0:
            return 0.0

        b = avg_win / avg_loss  # ratio of average win to average loss
        p = win_rate
        q = 1.0 - p

        kelly = (b * p - q) / b
        return kelly

    def calculate_position_size(
        self, signal, portfolio_value: float, config: dict
    ) -> KellyResult:
        """
        Calculate recommended position size using fractional Kelly.

        Args:
            signal: Signal dataclass with stake_usd and confidence
            portfolio_value: Total portfolio value in USD
            config: Configuration dict with strategy-specific overrides

        Returns:
            KellyResult with suggested stake and any cap applied
        """
        # Kelly multiplier (e.g., 0.25 = quarter-Kelly)
        kelly_multiplier = config.get('kelly_multiplier', 0.25)
        # Strategy-specific max position as fraction of portfolio
        max_position_pct = config.get('max_position_pct', 0.05)

        # Determine win rate and average win/loss from signal
        # Use confidence as a proxy for win rate
        win_rate = min(max(signal.confidence, 0.0), 1.0)

        # Calculate edge in dollars
        edge = abs(signal.edge_bps / 10000.0)  # edge in decimal
        # Approximate expected payoff structure
        # avg_win = stake * edge, avg_loss = stake (capped at stake)
        avg_win = signal.stake_usd * edge
        avg_loss = signal.stake_usd

        kelly_fraction = self.calculate_kelly_fraction(win_rate, avg_win, avg_loss)

        # Apply fractional Kelly
        fractional_kelly = kelly_fraction * kelly_multiplier

        # Cap to [0, 1] range for Kelly fraction (fraction of bankroll)
        # Negative Kelly means no edge, treat as 0
        if fractional_kelly < 0:
            fractional_kelly = 0.0
        if fractional_kelly > 1.0:
            fractional_kelly = 1.0

        # Calculate raw stake from Kelly fraction
        kelly_stake = portfolio_value * fractional_kelly

        # Apply strategy-specific max position cap
        cap_reason: str | None = None
        max_stake = portfolio_value * max_position_pct
        if kelly_stake > max_stake:
            kelly_stake = max_stake
            cap_reason = f"strategy_max_position_pct: capped at {max_position_pct * 100:.1f}% of portfolio (${max_stake:.2f})"

        # Additional safety cap: never stake more than the signal's original stake
        if kelly_stake > signal.stake_usd:
            kelly_stake = signal.stake_usd
            cap_reason = "signal_stake_cap: capped at original signal stake"

        # Ensure minimum stake
        if kelly_stake < 1.0:
            kelly_stake = 0.0

        return KellyResult(
            kelly_fraction=kelly_fraction,
            fractional_kelly=fractional_kelly,
            suggested_stake=round(kelly_stake, 2),
            cap_reason=cap_reason,
        )
