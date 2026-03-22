
from polyclaw.strategies.base import BaseStrategy
from polyclaw.strategies.registry import (
    StrategyRegistry,
    get_strategy,
    list_strategies,
    register,
)
from polyclaw.tests.test_base_strategy import DummyStrategy


def test_registry_singleton():
    r1 = StrategyRegistry()
    r2 = StrategyRegistry()
    assert r1 is r2


def test_register_and_get():
    StrategyRegistry.reset()
    strat = DummyStrategy()
    registry = StrategyRegistry()
    registry.register(strat)

    retrieved = registry.get('dummy')
    assert retrieved is strat
    assert retrieved is not None


def test_register_duplicate_overwrites():
    StrategyRegistry.reset()
    strat1 = DummyStrategy()
    strat2 = DummyStrategy()
    strat2._strategy_id = 'dummy'  # same ID

    registry = StrategyRegistry()
    registry.register(strat1)
    registry.register(strat2)

    assert registry.get('dummy') is strat2


def test_get_nonexistent():
    StrategyRegistry.reset()
    registry = StrategyRegistry()
    assert registry.get('nonexistent') is None


def test_list_all():
    StrategyRegistry.reset()

    class Dummy2(BaseStrategy):
        strategy_id = 'dummy2'
        name = 'Dummy 2'
        version = '1.0.0'

        @property
        def enabled(self) -> bool:
            return True

        def compute_features(self, market):
            return {}

        def generate_signals(self, market, features):
            return None

    registry = StrategyRegistry()
    registry.register(DummyStrategy())
    registry.register(Dummy2())

    all_strategies = registry.list_all()
    assert len(all_strategies) == 2
    ids = {s.strategy_id for s in all_strategies}
    assert ids == {'dummy', 'dummy2'}


def test_list_enabled():
    StrategyRegistry.reset()

    class DisabledDummy(BaseStrategy):
        strategy_id = 'disabled_dummy'
        name = 'Disabled Dummy'
        version = '1.0.0'

        @property
        def enabled(self) -> bool:
            return False

        def compute_features(self, market):
            return {}

        def generate_signals(self, market, features):
            return None

    registry = StrategyRegistry()
    registry.register(DummyStrategy(enabled=True, strategy_id='dummy1'))
    registry.register(DummyStrategy(enabled=True, strategy_id='dummy2'))
    registry.register(DisabledDummy())

    enabled = registry.list_enabled()
    assert len(enabled) == 2
    assert all(s.enabled for s in enabled)


def test_clear():
    StrategyRegistry.reset()
    registry = StrategyRegistry()
    registry.register(DummyStrategy())
    assert len(registry.list_all()) == 1

    registry.clear()
    assert len(registry.list_all()) == 0


def test_module_level_register():
    StrategyRegistry.reset()
    strat = DummyStrategy()
    register(strat)
    assert get_strategy('dummy') is strat


def test_module_level_get_strategy():
    StrategyRegistry.reset()
    assert get_strategy('nonexistent') is None


def test_module_level_list_strategies():
    StrategyRegistry.reset()
    strat = DummyStrategy()
    register(strat)

    all_s = list_strategies(enabled_only=False)
    assert len(all_s) == 1

    enabled_s = list_strategies(enabled_only=True)
    assert len(enabled_s) == 1


def test_module_level_list_strategies_enabled_only():
    StrategyRegistry.reset()

    class DisabledDummy(BaseStrategy):
        strategy_id = 'disabled'
        name = 'Disabled'
        version = '1.0.0'

        @property
        def enabled(self) -> bool:
            return False

        def compute_features(self, market):
            return {}

        def generate_signals(self, market, features):
            return None

    register(DummyStrategy())
    register(DisabledDummy())

    assert len(list_strategies(enabled_only=True)) == 1
    assert len(list_strategies(enabled_only=False)) == 2
