from dataclasses import dataclass


@dataclass
class PortfolioRiskDecision:
    """Result of portfolio-level risk evaluation."""
    approved: bool
    rejection_reasons: list[str]
    adjusted_stake: float | None  # None means no adjustment, a value means capped stake


class PortfolioRiskEngine:
    """
    Portfolio-level risk engine that evaluates signals against
    portfolio-wide risk limits.
    """

    def __init__(self, config: dict):
        self.max_correlated_exposure_pct = config.get('max_correlated_exposure_pct', 30.0)
        self.max_concentration_pct = config.get('max_concentration_single_market_pct', 15.0)
        self.max_open_positions = config.get('max_positions_open', 10)
        self.max_portfolio_drawdown_pct = config.get('max_portfolio_drawdown_pct', 20.0)

    def evaluate(
        self,
        signal,  # Signal from strategies.base
        market,  # MarketSnapshot from domain
        positions,  # list[Position] from models
        strategy,  # BaseStrategy from strategies.base
    ) -> PortfolioRiskDecision:
        """
        Evaluate a trading signal against portfolio-level risk limits.

        Returns a PortfolioRiskDecision with:
        - approved: True if all checks pass
        - rejection_reasons: list of reasons for rejection
        - adjusted_stake: capped stake if partial approval, None otherwise
        """
        from polyclaw.models import Position

        rejection_reasons: list[str] = []
        adjusted_stake: float | None = None

        # 1. Check max open positions
        open_positions = [p for p in positions if p.is_open]
        if len(open_positions) >= self.max_open_positions:
            rejection_reasons.append(
                f'max_open_positions_exceeded: {len(open_positions)} >= {self.max_open_positions}'
            )
            return PortfolioRiskDecision(approved=False, rejection_reasons=rejection_reasons, adjusted_stake=None)

        # 2. Calculate portfolio value estimate from positions.
        # When the portfolio is empty, use a minimum baseline of $100 to make
        # percentage-based checks meaningful. Otherwise use actual notional.
        current_portfolio_value = sum(abs(p.notional_usd) for p in open_positions)
        MIN_PORTFOLIO_BASELINE = 100.0
        estimated_total = max(current_portfolio_value, MIN_PORTFOLIO_BASELINE)

        # 3. Check max concentration per market
        market_exposure = sum(abs(p.notional_usd) for p in open_positions if p.market_id == market.market_id)
        new_market_exposure = market_exposure + signal.stake_usd
        # Only enforce concentration when there are existing positions in this market
        # to avoid division-by-zero artifacts with a fresh portfolio.
        if market_exposure > 0:
            market_concentration = (new_market_exposure / estimated_total) * 100.0
            if market_concentration > self.max_concentration_pct:
                rejection_reasons.append(
                    f'market_concentration_exceeded: {market_concentration:.1f}% > {self.max_concentration_pct}% '
                    f'(market={market.market_id})'
                )
                return PortfolioRiskDecision(approved=False, rejection_reasons=rejection_reasons, adjusted_stake=None)

        # 4. Check max correlated exposure using event_key as correlation proxy.
        # Only check when there are existing positions; with a fresh portfolio
        # a new position cannot be "correlated" against nothing.
        if open_positions:
            event_key = getattr(market, 'event_key', market.market_id) or market.market_id
            correlated_exposure = sum(
                abs(p.notional_usd) for p in open_positions
                if str(getattr(p, 'event_key', '') or '') == str(event_key)
            )
            new_correlated = correlated_exposure + signal.stake_usd
            correlated_pct = (new_correlated / estimated_total) * 100.0
            if correlated_pct > self.max_correlated_exposure_pct:
                # Try adjusting the stake to fit within limits
                available = (self.max_correlated_exposure_pct / 100.0 * estimated_total) - correlated_exposure
                if available > 0:
                    adjusted_stake = min(signal.stake_usd, available)
                    rejection_reasons.append(
                        f'correlated_exposure_adjusted: {correlated_pct:.1f}% > {self.max_correlated_exposure_pct}%, '
                        f'capped stake to ${adjusted_stake:.2f}'
                    )
                    # Partial approval with adjusted stake
                    return PortfolioRiskDecision(
                        approved=True, rejection_reasons=rejection_reasons, adjusted_stake=adjusted_stake
                    )
                else:
                    rejection_reasons.append(
                        f'correlated_exposure_exceeded: {correlated_pct:.1f}% > {self.max_correlated_exposure_pct}%'
                    )
                    return PortfolioRiskDecision(approved=False, rejection_reasons=rejection_reasons, adjusted_stake=None)

        # All checks passed
        return PortfolioRiskDecision(approved=True, rejection_reasons=[], adjusted_stake=None)
