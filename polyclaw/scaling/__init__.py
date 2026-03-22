"""PolyClaw Scaling Package — automated stage management, market expansion, and fee optimization."""

from polyclaw.scaling.manager import ScalingManager
from polyclaw.scaling.evaluator import PerformanceEvaluator
from polyclaw.scaling.expansion import MarketExpander, MarketExpansionSuggestion
from polyclaw.scaling.slippage_monitor import SlippageMonitor, SlippageRecord
from polyclaw.scaling.fee_calculator import FeeCalculator, FeeBreakdown

__all__ = [
    'ScalingManager',
    'PerformanceEvaluator',
    'MarketExpander',
    'MarketExpansionSuggestion',
    'SlippageMonitor',
    'SlippageRecord',
    'FeeCalculator',
    'FeeBreakdown',
]
