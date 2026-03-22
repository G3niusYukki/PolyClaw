from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.strategies.event_catalyst import EventCatalystStrategy
from polyclaw.strategies.features import FeatureCache, FeatureEngine
from polyclaw.strategies.liquidity_momentum import LiquidityMomentumStrategy
from polyclaw.strategies.registry import (
    StrategyRegistry,
    get_strategy,
    list_strategies,
    register,
)

# Manually register known strategies with the global registry.
StrategyRegistry().register(EventCatalystStrategy())
StrategyRegistry().register(LiquidityMomentumStrategy())

__all__ = [
    'BaseStrategy',
    'Side',
    'Signal',
    'StrategyRegistry',
    'register',
    'get_strategy',
    'list_strategies',
    'EventCatalystStrategy',
    'LiquidityMomentumStrategy',
    'FeatureEngine',
    'FeatureCache',
]
