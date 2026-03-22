from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from polyclaw.db import Base
from polyclaw.domain import MarketSnapshot
from polyclaw.models import Order, Position
from polyclaw.risk.portfolio import PortfolioRiskDecision, PortfolioRiskEngine
from polyclaw.risk.clusters import ClusterExposure, EventClusterTracker, extract_cluster_from_title
from polyclaw.risk.sizing import KellyPositionSizer, KellyResult
from polyclaw.risk.config import (
    GlobalLimits,
    MarketQualityLimits,
    PortfolioLimits,
    RiskConfig,
    StrategyLimits,
    load_risk_config,
)
from polyclaw.safety import (
    GlobalCircuitBreaker,
    StrategyCircuitBreaker,
    _circuit_state,
)
from polyclaw.strategies.base import BaseStrategy, Signal, Side
from polyclaw.timeutils import utcnow


def make_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ---------------------------------------------------------------------------
# Mock strategy for testing
# ---------------------------------------------------------------------------

class MockStrategy(BaseStrategy):
    @property
    def strategy_id(self) -> str:
        return 'test_strategy'

    @property
    def name(self) -> str:
        return 'Test Strategy'

    @property
    def version(self) -> str:
        return '1.0.0'

    @property
    def max_position_pct(self) -> float:
        return 0.05

    def compute_features(self, market):
        return {}

    def generate_signals(self, market, features):
        return None


# ---------------------------------------------------------------------------
# PortfolioRiskEngine tests
# ---------------------------------------------------------------------------

def test_portfolio_risk_approves_when_all_checks_pass():
    session = make_session()
    engine = PortfolioRiskEngine({
        'max_correlated_exposure_pct': 30.0,
        'max_concentration_single_market_pct': 15.0,
        'max_positions_open': 10,
        'max_portfolio_drawdown_pct': 20.0,
    })

    market = MarketSnapshot(
        market_id='m1', title='Test', description='', yes_price=0.5, no_price=0.5,
        spread_bps=50, liquidity_usd=10000, volume_24h_usd=1000,
        category='test', event_key='e1', closes_at=None, fetched_at=utcnow(),
    )
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.8, edge_bps=500,
        explanation='test', market_id='m1', stake_usd=5.0,
    )
    strategy = MockStrategy()
    positions = []

    decision = engine.evaluate(signal, market, positions, strategy)
    assert decision.approved is True
    assert decision.rejection_reasons == []
    assert decision.adjusted_stake is None


def test_portfolio_risk_rejects_max_open_positions():
    engine = PortfolioRiskEngine({
        'max_correlated_exposure_pct': 30.0,
        'max_concentration_single_market_pct': 15.0,
        'max_positions_open': 2,
        'max_portfolio_drawdown_pct': 20.0,
    })

    market = MarketSnapshot(
        market_id='m1', title='Test', description='', yes_price=0.5, no_price=0.5,
        spread_bps=50, liquidity_usd=10000, volume_24h_usd=1000,
        category='test', event_key='e1', closes_at=None, fetched_at=utcnow(),
    )
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.8, edge_bps=500,
        explanation='test', market_id='m1', stake_usd=10.0,
    )
    strategy = MockStrategy()
    positions = [
        MagicMock(spec=Position, is_open=True, market_id='p1', notional_usd=10, event_key='e1'),
        MagicMock(spec=Position, is_open=True, market_id='p2', notional_usd=10, event_key='e2'),
    ]

    decision = engine.evaluate(signal, market, positions, strategy)
    assert decision.approved is False
    assert any('max_open_positions_exceeded' in r for r in decision.rejection_reasons)


def test_portfolio_risk_blocks_market_concentration():
    engine = PortfolioRiskEngine({
        'max_correlated_exposure_pct': 30.0,
        'max_concentration_single_market_pct': 15.0,
        'max_positions_open': 10,
        'max_portfolio_drawdown_pct': 20.0,
    })

    market = MarketSnapshot(
        market_id='m1', title='Test', description='', yes_price=0.5, no_price=0.5,
        spread_bps=50, liquidity_usd=10000, volume_24h_usd=1000,
        category='test', event_key='e1', closes_at=None, fetched_at=utcnow(),
    )
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.8, edge_bps=500,
        explanation='test', market_id='m1', stake_usd=10.0,
    )
    strategy = MockStrategy()
    # Existing position in the same market consuming 14% + new 10% > 15% limit
    positions = [
        MagicMock(spec=Position, is_open=True, market_id='m1', notional_usd=14, event_key='e1'),
    ]

    decision = engine.evaluate(signal, market, positions, strategy)
    assert decision.approved is False
    assert any('market_concentration_exceeded' in r for r in decision.rejection_reasons)


def test_portfolio_risk_blocks_correlated_exposure():
    engine = PortfolioRiskEngine({
        'max_correlated_exposure_pct': 30.0,
        'max_concentration_single_market_pct': 15.0,
        'max_positions_open': 10,
        'max_portfolio_drawdown_pct': 20.0,
    })

    market = MarketSnapshot(
        market_id='m2', title='Test', description='', yes_price=0.5, no_price=0.5,
        spread_bps=50, liquidity_usd=10000, volume_24h_usd=1000,
        category='test', event_key='shared-event', closes_at=None, fetched_at=utcnow(),
    )
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.8, edge_bps=500,
        explanation='test', market_id='m2', stake_usd=5.0,
    )
    strategy = MockStrategy()
    # existing=35, signal=5, estimated_total=100 (baseline since 35<100)
    # correlated=40/100=40% > 30% -> BLOCKED
    positions = [
        MagicMock(spec=Position, is_open=True, market_id='m1', notional_usd=35, event_key='shared-event'),
    ]

    decision = engine.evaluate(signal, market, positions, strategy)
    assert decision.approved is False
    assert any('correlated_exposure_exceeded' in r for r in decision.rejection_reasons)


def test_portfolio_risk_adjusts_stake_when_possible():
    """When correlated exposure exceeds but partial position fits."""
    engine = PortfolioRiskEngine({
        'max_correlated_exposure_pct': 30.0,
        'max_concentration_single_market_pct': 15.0,
        'max_positions_open': 10,
        'max_portfolio_drawdown_pct': 20.0,
    })

    market = MarketSnapshot(
        market_id='m2', title='Test', description='', yes_price=0.5, no_price=0.5,
        spread_bps=50, liquidity_usd=10000, volume_24h_usd=1000,
        category='test', event_key='shared-event', closes_at=None, fetched_at=utcnow(),
    )
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.8, edge_bps=500,
        explanation='test', market_id='m2', stake_usd=10.0,
    )
    strategy = MockStrategy()
    # existing=50, signal=10, estimated_total=100 (baseline since 50<100)
    # market concentration: m2=10/100=10% < 15% -> OK
    # correlated=60/100=60% > 30% -> exceeds
    # available = 30 - 50 = -20 < 0 -> no partial, reject
    # Try: existing=5, signal=10, estimated_total=100
    # market concentration: m2=10/100=10% < 15% -> OK
    # correlated=15/100=15% < 30% -> OK -> approved
    positions = [
        MagicMock(spec=Position, is_open=True, market_id='m1', notional_usd=5, event_key='shared-event'),
    ]

    decision = engine.evaluate(signal, market, positions, strategy)
    assert decision.approved is True
    assert len(decision.rejection_reasons) == 0
    assert decision.adjusted_stake is None


# ---------------------------------------------------------------------------
# EventClusterTracker tests
# ---------------------------------------------------------------------------

def test_extract_cluster_from_title_presidential_election():
    assert extract_cluster_from_title("Who wins 2024 US Presidential Election") == '2024-us-presidential-election'
    # Year only when no specific cluster pattern matches
    assert extract_cluster_from_title("Random question about 2024") == '2024'
    assert extract_cluster_from_title("Random market about tech") == 'general'


def test_extract_cluster_from_title_bitcoin():
    # Year followed immediately by keyword
    assert extract_cluster_from_title("2024 Bitcoin", "") == '2024-bitcoin'
    # Year separated from keyword: falls back to year only
    assert extract_cluster_from_title("Bitcoin price in 2024", "") == '2024'


def test_extract_cluster_from_title_year_only():
    key = extract_cluster_from_title("Random market about tech", "general")
    assert key == 'general'


def test_event_cluster_map_and_get():
    session = make_session()
    tracker = EventClusterTracker(session)

    # Map some markets to clusters
    tracker.map_market_to_cluster('market1', '2024-us-presidential-election')
    tracker.map_market_to_cluster('market2', '2024-us-presidential-election')
    tracker.map_market_to_cluster('market3', '2024-bitcoin')
    session.commit()

    clusters = tracker.get_all_clusters()
    assert '2024-us-presidential-election' in clusters
    assert '2024-bitcoin' in clusters
    assert len(clusters) == 2


def test_event_cluster_exposure():
    session = make_session()
    tracker = EventClusterTracker(session)

    tracker.map_market_to_cluster('m1', '2024-us-presidential-election')
    tracker.map_market_to_cluster('m2', '2024-us-presidential-election')
    tracker.map_market_to_cluster('m3', '2024-bitcoin')
    session.commit()

    positions = [
        MagicMock(spec=Position, is_open=True, market_id='m1', notional_usd=50, event_key='e1'),
        MagicMock(spec=Position, is_open=True, market_id='m2', notional_usd=30, event_key='e2'),
        MagicMock(spec=Position, is_open=True, market_id='m3', notional_usd=20, event_key='e3'),
        MagicMock(spec=Position, is_open=True, market_id='m4', notional_usd=10, event_key='e4'),
    ]

    election_exposure = tracker.get_cluster_exposure('2024-us-presidential-election', positions)
    assert election_exposure == 80.0  # 50 + 30

    btc_exposure = tracker.get_cluster_exposure('2024-bitcoin', positions)
    assert btc_exposure == 20.0


def test_cluster_exposure_summary():
    session = make_session()
    tracker = EventClusterTracker(session)
    tracker.map_market_to_cluster('m1', '2024-us-presidential-election')
    session.commit()

    positions = [
        MagicMock(spec=Position, is_open=True, market_id='m1', notional_usd=50, event_key='e1'),
    ]

    summary = tracker.get_cluster_exposure_summary('2024-us-presidential-election', positions, max_allowed_pct=30.0)
    assert summary.cluster_key == '2024-us-presidential-election'
    assert summary.exposure_usd == 50.0
    assert summary.position_count == 1
    assert summary.max_allowed_pct == 30.0


# ---------------------------------------------------------------------------
# KellyPositionSizer tests
# ---------------------------------------------------------------------------

def test_kelly_fraction_calculation():
    sizer = KellyPositionSizer()

    # 60% win rate with 2:1 payoff: f* = (2*0.6 - 0.4) / 2 = (1.2 - 0.4) / 2 = 0.4
    f = sizer.calculate_kelly_fraction(win_rate=0.6, avg_win=2.0, avg_loss=1.0)
    assert abs(f - 0.4) < 0.001

    # 50% win rate = no edge: f* = 0
    f = sizer.calculate_kelly_fraction(win_rate=0.5, avg_win=1.0, avg_loss=1.0)
    assert abs(f) < 0.001

    # 40% win rate with even payoff: negative Kelly (bad bet)
    f = sizer.calculate_kelly_fraction(win_rate=0.4, avg_win=1.0, avg_loss=1.0)
    assert f < 0

    # Zero loss prevents calculation
    f = sizer.calculate_kelly_fraction(win_rate=0.6, avg_win=2.0, avg_loss=0.0)
    assert f == 0.0


def test_kelly_position_sizing_within_limits():
    sizer = KellyPositionSizer()
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.7, edge_bps=1000,
        explanation='test', market_id='m1', stake_usd=50.0,
    )
    portfolio_value = 1000.0
    config = {'kelly_multiplier': 0.25, 'max_position_pct': 0.05}

    result = sizer.calculate_position_size(signal, portfolio_value, config)

    assert result.suggested_stake >= 0
    assert result.suggested_stake <= portfolio_value * config['max_position_pct']
    assert 0.0 <= result.fractional_kelly <= 1.0


def test_kelly_position_size_respects_cap():
    sizer = KellyPositionSizer()
    # High confidence signal with large stake
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.95, edge_bps=2000,
        explanation='test', market_id='m1', stake_usd=100.0,
    )
    portfolio_value = 1000.0
    config = {'kelly_multiplier': 0.5, 'max_position_pct': 0.05}

    result = sizer.calculate_position_size(signal, portfolio_value, config)

    # Should be capped at max_position_pct (5% of $1000 = $50)
    assert result.suggested_stake <= 50.0
    assert result.cap_reason is not None


def test_kelly_zero_confidence():
    sizer = KellyPositionSizer()
    signal = Signal(
        strategy_id='test', side=Side.YES, confidence=0.0, edge_bps=100,
        explanation='test', market_id='m1', stake_usd=10.0,
    )
    result = sizer.calculate_position_size(signal, 1000.0, {'kelly_multiplier': 0.25, 'max_position_pct': 0.05})
    assert result.suggested_stake == 0.0
    assert result.fractional_kelly == 0.0


# ---------------------------------------------------------------------------
# RiskConfig tests
# ---------------------------------------------------------------------------

def test_risk_config_defaults():
    config = RiskConfig()
    assert config.global_limits.max_portfolio_drawdown_pct == 20.0
    assert config.global_limits.max_daily_loss_usd == 500.0
    assert config.portfolio_limits.max_correlated_exposure_pct == 30.0
    assert config.portfolio_limits.max_positions_open == 10
    assert config.market_quality_limits.min_liquidity_usd == 5000.0
    assert config.market_quality_limits.max_spread_bps == 300


def test_load_risk_config_from_yaml(tmp_path):
    try:
        import yaml
    except ImportError:
        import pytest
        pytest.skip("PyYAML not installed")

    yaml_content = """
global:
  max_portfolio_drawdown_pct: 25.0
  max_daily_loss_usd: 1000.0
  max_data_latency_minutes: 20

portfolio:
  max_correlated_exposure_pct: 35.0
  max_concentration_single_market_pct: 20.0
  max_positions_open: 15

strategy:
  max_strategy_drawdown_pct: 12.0
  max_exec_failure_rate: 0.25
  auto_reset_after_hours: 48

market_quality:
  min_liquidity_usd: 10000.0
  max_spread_bps: 200
  min_volume_24h_usd: 2000.0
"""
    yaml_path = tmp_path / 'test_risk.yaml'
    yaml_path.write_text(yaml_content)

    config = load_risk_config(str(yaml_path))

    assert config.global_limits.max_portfolio_drawdown_pct == 25.0
    assert config.global_limits.max_daily_loss_usd == 1000.0
    assert config.portfolio_limits.max_correlated_exposure_pct == 35.0
    assert config.portfolio_limits.max_positions_open == 15
    assert config.strategy_limits.max_exec_failure_rate == 0.25
    assert config.market_quality_limits.min_liquidity_usd == 10000.0


def test_load_risk_config_validation(tmp_path):
    try:
        import yaml
    except ImportError:
        import pytest
        pytest.skip("PyYAML not installed")

    yaml_path = tmp_path / 'invalid.yaml'
    yaml_path.write_text("global:\n  max_portfolio_drawdown_pct: -5.0\n")

    try:
        load_risk_config(str(yaml_path))
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "max_portfolio_drawdown_pct must be positive" in str(e)


# ---------------------------------------------------------------------------
# Circuit Breaker tests
# ---------------------------------------------------------------------------

def test_global_circuit_breaker_triggers_on_drawdown():
    session = make_session()
    cb = GlobalCircuitBreaker(max_drawdown_pct=20.0)
    _circuit_state.reset_global()

    # Drawdown of 25% should trigger
    triggered = cb.check(
        session, portfolio_value=1000, portfolio_drawdown_pct=25.0,
        latest_data_fetched_at=utcnow(), recent_orders=[],
    )
    assert triggered is True
    assert cb.is_triggered() is True
    assert 'portfolio_drawdown_exceeded' in cb.get_trigger_reason()


def test_global_circuit_breaker_all_checks_pass():
    session = make_session()
    cb = GlobalCircuitBreaker(
        max_drawdown_pct=20.0,
        max_daily_loss_usd=500.0,
        max_data_latency_minutes=15,
        max_exec_failure_rate=0.20,
    )
    _circuit_state.reset_global()

    recent_orders = [
        MagicMock(spec=Order, status='filled', submitted_at=utcnow()),
        MagicMock(spec=Order, status='filled', submitted_at=utcnow()),
        MagicMock(spec=Order, status='filled', submitted_at=utcnow()),
        MagicMock(spec=Order, status='filled', submitted_at=utcnow()),
    ]

    triggered = cb.check(
        session, portfolio_value=1000, portfolio_drawdown_pct=5.0,
        latest_data_fetched_at=utcnow(), recent_orders=recent_orders,
    )
    assert triggered is False
    assert cb.is_triggered() is False


def test_global_circuit_breaker_triggers_on_data_staleness():
    session = make_session()
    cb = GlobalCircuitBreaker(max_data_latency_minutes=15)
    _circuit_state.reset_global()

    stale_data = utcnow() - timedelta(minutes=20)
    triggered = cb.check(
        session, portfolio_value=1000, portfolio_drawdown_pct=5.0,
        latest_data_fetched_at=stale_data, recent_orders=[],
    )
    assert triggered is True
    assert 'data_stale' in cb.get_trigger_reason()


def test_global_circuit_breaker_triggers_on_exec_failure_rate():
    session = make_session()
    cb = GlobalCircuitBreaker(max_exec_failure_rate=0.20)
    _circuit_state.reset_global()

    # 3 failed out of 4 orders = 75% failure rate
    recent_orders = [
        MagicMock(spec=Order, status='failed'),
        MagicMock(spec=Order, status='failed'),
        MagicMock(spec=Order, status='failed'),
        MagicMock(spec=Order, status='filled'),
    ]
    triggered = cb.check(
        session, portfolio_value=1000, portfolio_drawdown_pct=5.0,
        latest_data_fetched_at=utcnow(), recent_orders=recent_orders,
    )
    assert triggered is True
    assert 'exec_failure_rate_exceeded' in cb.get_trigger_reason()


def test_global_circuit_breaker_manual_reset():
    session = make_session()
    cb = GlobalCircuitBreaker(max_drawdown_pct=20.0)
    _circuit_state.reset_global()

    cb.check(session, portfolio_value=1000, portfolio_drawdown_pct=30.0,
             latest_data_fetched_at=utcnow(), recent_orders=[])
    assert cb.is_triggered() is True

    cb.reset()
    assert cb.is_triggered() is False
    assert cb.get_trigger_reason() == ''


def test_strategy_circuit_breaker_triggers_on_drawdown():
    session = make_session()
    _circuit_state.reset_strategy('test-strategy')
    cb = StrategyCircuitBreaker('test-strategy', max_drawdown_pct=10.0)
    _circuit_state.reset_strategy('test-strategy')

    triggered = cb.check(
        session, strategy_drawdown_pct=15.0, recent_orders=[],
    )
    assert triggered is True
    assert cb.is_triggered() is True
    assert 'strategy_drawdown_exceeded' in cb.get_trigger_reason()


def test_strategy_circuit_breaker_auto_reset_window():
    session = make_session()
    _circuit_state.reset_strategy('test-strategy')
    cb = StrategyCircuitBreaker('test-strategy', auto_reset_after_hours=24)
    _circuit_state.reset_strategy('test-strategy')

    # Trigger it
    cb.check(session, strategy_drawdown_pct=15.0, recent_orders=[])
    assert cb.is_triggered() is True

    # Simulate time passing (manipulate internal state)
    import polyclaw.safety as safety_module
    if 'test-strategy' in safety_module._circuit_state._strategy_states:
        safety_module._circuit_state._strategy_states['test-strategy']['triggered_at'] = (
            utcnow() - timedelta(hours=25)
        )

    # Check again should see auto-reset eligible
    triggered = cb.check(session, strategy_drawdown_pct=5.0, recent_orders=[])
    # Should not re-trigger since drawdown is fine and auto-reset cleared the state
    assert cb.is_triggered() is False  # Auto-reset cleared triggered flag
    assert cb.is_awaiting_manual_review() is False


def test_strategy_circuit_breaker_exec_failure_rate():
    session = make_session()
    _circuit_state.reset_strategy('test-strategy2')
    cb = StrategyCircuitBreaker('test-strategy2', max_exec_failure_rate=0.20)
    _circuit_state.reset_strategy('test-strategy2')

    recent_orders = [
        MagicMock(spec=Order, status='failed'),
        MagicMock(spec=Order, status='failed'),
        MagicMock(spec=Order, status='filled'),
        MagicMock(spec=Order, status='filled'),
    ]
    triggered = cb.check(session, strategy_drawdown_pct=5.0, recent_orders=recent_orders)
    assert triggered is True
    assert 'strategy_exec_failure_rate_exceeded' in cb.get_trigger_reason()


def test_strategy_circuit_breaker_manual_reset():
    session = make_session()
    _circuit_state.reset_strategy('test-strategy')
    cb = StrategyCircuitBreaker('test-strategy', max_drawdown_pct=10.0)
    _circuit_state.reset_strategy('test-strategy')

    cb.check(session, strategy_drawdown_pct=15.0, recent_orders=[])
    assert cb.is_triggered() is True

    cb.reset()
    assert cb.is_triggered() is False


def test_strategy_circuit_breaker_check_and_allow():
    session = make_session()
    _circuit_state.reset_strategy('test-strategy3')
    cb = StrategyCircuitBreaker('test-strategy3')
    _circuit_state.reset_strategy('test-strategy3')

    # Initially should allow
    assert cb.check_and_allow(session) is True

    # Trigger it
    cb.check(session, strategy_drawdown_pct=15.0, recent_orders=[])
    assert cb.is_triggered() is True

    # Should block
    assert cb.check_and_allow(session) is False

    # Reset and allow again
    cb.reset()
    assert cb.check_and_allow(session) is True
