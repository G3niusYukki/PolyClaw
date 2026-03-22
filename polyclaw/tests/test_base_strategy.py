
import pytest

from polyclaw.domain import MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal


class DummyStrategy(BaseStrategy):
    """Concrete implementation of BaseStrategy for testing."""

    strategy_id = 'dummy'
    name = 'Dummy Strategy'
    version = '1.0.0'

    def __init__(self, enabled: bool = True, strategy_id: str | None = None):
        self._enabled = enabled
        if strategy_id is not None:
            self.strategy_id = strategy_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {'dummy_feature': market.yes_price * 2}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        if market.yes_price > 0.7:
            return Signal(
                strategy_id=self.strategy_id,
                side=Side.YES,
                confidence=0.75,
                edge_bps=500,
                explanation='Test signal.',
                features_used=features,
            )
        return None


def test_signal_dataclass():
    sig = Signal(
        strategy_id='test',
        side=Side.YES,
        confidence=0.8,
        edge_bps=1000,
        explanation='Test explanation.',
        features_used={'foo': 1.0},
    )
    assert sig.strategy_id == 'test'
    assert sig.side == Side.YES
    assert sig.confidence == 0.8
    assert sig.edge_bps == 1000
    assert sig.explanation == 'Test explanation.'
    assert sig.features_used == {'foo': 1.0}


def test_side_enum():
    assert Side.YES.value == 'yes'
    assert Side.NO.value == 'no'
    assert Side.YES == 'yes'
    assert Side.NO == 'no'


def test_base_strategy_properties():
    strat = DummyStrategy()
    assert strat.strategy_id == 'dummy'
    assert strat.name == 'Dummy Strategy'
    assert strat.version == '1.0.0'
    assert strat.enabled is True
    assert strat.validate() is True


def test_base_strategy_disabled():
    strat = DummyStrategy(enabled=False)
    assert strat.enabled is False
    assert strat.validate() is False


def test_compute_features_abstract():
    with pytest.raises(TypeError):
        BaseStrategy()


def test_generate_signals_abstract():
    with pytest.raises(TypeError):
        BaseStrategy()


def test_dummy_strategy_signal_generation(sample_market):
    strat = DummyStrategy()
    features = strat.compute_features(sample_market)
    assert features == {'dummy_feature': sample_market.yes_price * 2}

    signal = strat.generate_signals(sample_market, features)
    # sample_market yes_price is 0.55, not > 0.7, so no signal
    assert signal is None

    # Now with high price
    sample_market.yes_price = 0.75
    signal = strat.generate_signals(sample_market, features)
    assert signal is not None
    assert signal.side == Side.YES
    assert signal.confidence == 0.75
    assert signal.edge_bps == 500
    assert signal.features_used == features


def test_dummy_strategy_no_signal_below_threshold(low_liquidity_market):
    strat = DummyStrategy()
    signal = strat.generate_signals(low_liquidity_market, {})
    assert signal is None
