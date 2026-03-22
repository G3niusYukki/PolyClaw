from dataclasses import dataclass, field
from typing import Any


@dataclass
class GlobalLimits:
    """Global risk limits."""
    max_portfolio_drawdown_pct: float = 20.0
    max_daily_loss_usd: float = 500.0
    max_data_latency_minutes: int = 15


@dataclass
class PortfolioLimits:
    """Portfolio-level risk limits."""
    max_correlated_exposure_pct: float = 30.0
    max_concentration_single_market_pct: float = 15.0
    max_positions_open: int = 10
    max_portfolio_drawdown_pct: float = 20.0


@dataclass
class StrategyLimits:
    """Strategy-level risk limits."""
    max_strategy_drawdown_pct: float = 10.0
    max_exec_failure_rate: float = 0.20
    auto_reset_after_hours: int = 24


@dataclass
class MarketQualityLimits:
    """Market quality thresholds."""
    min_liquidity_usd: float = 5000.0
    max_spread_bps: int = 300
    min_volume_24h_usd: float = 1000.0


@dataclass
class RiskConfig:
    """Aggregated risk configuration."""
    global_limits: GlobalLimits = field(default_factory=GlobalLimits)
    portfolio_limits: PortfolioLimits = field(default_factory=PortfolioLimits)
    strategy_limits: StrategyLimits = field(default_factory=StrategyLimits)
    market_quality_limits: MarketQualityLimits = field(default_factory=MarketQualityLimits)


def _normalize_value(val: Any, default: Any) -> Any:
    """Normalize a config value, converting from YAML snake_case to dataclass camelCase."""
    if val is None:
        return default
    return val


def load_risk_config(path: str = "RISK_CONFIG.yaml") -> RiskConfig:
    """Load risk configuration from a YAML file, validating all values."""
    try:
        import yaml
    except ImportError:
        import sys
        sys.exit("PyYAML is required to load risk config")

    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}

    # Global limits
    raw_global = raw.get('global', {})
    global_limits = GlobalLimits(
        max_portfolio_drawdown_pct=_normalize_value(raw_global.get('max_portfolio_drawdown_pct'), 20.0),
        max_daily_loss_usd=_normalize_value(raw_global.get('max_daily_loss_usd'), 500.0),
        max_data_latency_minutes=_normalize_value(raw_global.get('max_data_latency_minutes'), 15),
    )

    # Portfolio limits
    raw_portfolio = raw.get('portfolio', {})
    portfolio_limits = PortfolioLimits(
        max_correlated_exposure_pct=_normalize_value(raw_portfolio.get('max_correlated_exposure_pct'), 30.0),
        max_concentration_single_market_pct=_normalize_value(raw_portfolio.get('max_concentration_single_market_pct'), 15.0),
        max_positions_open=_normalize_value(raw_portfolio.get('max_positions_open'), 10),
        max_portfolio_drawdown_pct=_normalize_value(raw_portfolio.get('max_portfolio_drawdown_pct'), 20.0),
    )

    # Strategy limits
    raw_strategy = raw.get('strategy', {})
    strategy_limits = StrategyLimits(
        max_strategy_drawdown_pct=_normalize_value(raw_strategy.get('max_strategy_drawdown_pct'), 10.0),
        max_exec_failure_rate=_normalize_value(raw_strategy.get('max_exec_failure_rate'), 0.20),
        auto_reset_after_hours=_normalize_value(raw_strategy.get('auto_reset_after_hours'), 24),
    )

    # Market quality limits
    raw_market = raw.get('market_quality', {})
    market_quality_limits = MarketQualityLimits(
        min_liquidity_usd=_normalize_value(raw_market.get('min_liquidity_usd'), 5000.0),
        max_spread_bps=_normalize_value(raw_market.get('max_spread_bps'), 300),
        min_volume_24h_usd=_normalize_value(raw_market.get('min_volume_24h_usd'), 1000.0),
    )

    # Validate positive values
    if global_limits.max_portfolio_drawdown_pct <= 0:
        raise ValueError("global.max_portfolio_drawdown_pct must be positive")
    if global_limits.max_daily_loss_usd <= 0:
        raise ValueError("global.max_daily_loss_usd must be positive")
    if global_limits.max_data_latency_minutes <= 0:
        raise ValueError("global.max_data_latency_minutes must be positive")
    if portfolio_limits.max_correlated_exposure_pct <= 0:
        raise ValueError("portfolio.max_correlated_exposure_pct must be positive")
    if portfolio_limits.max_concentration_single_market_pct <= 0:
        raise ValueError("portfolio.max_concentration_single_market_pct must be positive")
    if portfolio_limits.max_positions_open <= 0:
        raise ValueError("portfolio.max_positions_open must be positive")
    if market_quality_limits.min_liquidity_usd < 0:
        raise ValueError("market_quality.min_liquidity_usd cannot be negative")
    if market_quality_limits.max_spread_bps <= 0:
        raise ValueError("market_quality.max_spread_bps must be positive")
    if market_quality_limits.min_volume_24h_usd < 0:
        raise ValueError("market_quality.min_volume_24h_usd cannot be negative")

    return RiskConfig(
        global_limits=global_limits,
        portfolio_limits=portfolio_limits,
        strategy_limits=strategy_limits,
        market_quality_limits=market_quality_limits,
    )
