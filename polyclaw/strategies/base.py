from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from polyclaw.domain import MarketSnapshot


class Side(str, Enum):
    YES = 'yes'
    NO = 'no'


@dataclass
class Signal:
    strategy_id: str
    side: Side
    confidence: float
    edge_bps: int
    explanation: str
    market_id: str = ''
    model_probability: float = 0.5
    market_implied_probability: float = 0.5
    stake_usd: float = 0.0
    features_used: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this strategy."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string for this strategy."""
        ...

    @property
    def max_position_pct(self) -> float:
        """Maximum position size as fraction of portfolio (e.g. 0.05 = 5%)."""
        return 0.05

    @property
    def enabled(self) -> bool:
        """Whether this strategy is currently enabled."""
        return True

    @abstractmethod
    def compute_features(self, market: MarketSnapshot) -> dict:
        """Compute strategy-specific features from a market snapshot.

        Args:
            market: The market snapshot to analyze.

        Returns:
            Dictionary of feature name -> feature value.
        """
        ...

    @abstractmethod
    def generate_signals(self, market: MarketSnapshot, features: dict) -> 'Signal | None':
        """Generate a trading signal from computed features.

        Args:
            market: The market snapshot.
            features: Pre-computed features from compute_features().

        Returns:
            Signal if a trade is warranted, None otherwise.
        """
        ...

    def validate(self) -> bool:
        """Validate that the strategy is properly configured.

        Returns:
            True if the strategy is valid and can operate.
        """
        return self.enabled
