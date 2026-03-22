"""Tests for scaling manager, performance evaluator, market expansion, and fee calculator."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from polyclaw.db import Base
from polyclaw.execution.orders import OrderSpec, OrderType
from polyclaw.models import Market, MarketWhitelistRecord, ShadowResult
from polyclaw.scaling.evaluator import PerformanceEvaluator
from polyclaw.scaling.expansion import MarketExpander
from polyclaw.scaling.fee_calculator import FeeBreakdown, FeeCalculator
from polyclaw.scaling.manager import ScalingManager
from polyclaw.timeutils import utcnow


@pytest.fixture
def scaling_session():
    """Create a fresh in-memory SQLite database for scaling tests."""
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class TestPerformanceEvaluator:
    """Tests for PerformanceEvaluator."""

    def test_is_profitable_empty(self, scaling_session):
        ev = PerformanceEvaluator()
        assert ev.is_profitable(scaling_session) is False

    def test_is_profitable_positive(self, scaling_session):
        now = utcnow()
        for i in range(3):
            scaling_session.add(ShadowResult(
                market_id=f'mkt-{i}',
                strategy_id='s1',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=1.0,
                accuracy=True,
                resolved_at=now - timedelta(days=i),
                created_at=now,
            ))
        scaling_session.commit()

        ev = PerformanceEvaluator()
        assert ev.is_profitable(scaling_session) is True

    def test_is_profitable_negative(self, scaling_session):
        now = utcnow()
        for i in range(3):
            scaling_session.add(ShadowResult(
                market_id=f'mkt-{i}',
                strategy_id='s1',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='no',
                pnl=-0.50,
                accuracy=False,
                resolved_at=now - timedelta(days=i),
                created_at=now,
            ))
        scaling_session.commit()

        ev = PerformanceEvaluator()
        assert ev.is_profitable(scaling_session) is False

    def test_sharpe_acceptable_insufficient_data(self, scaling_session):
        ev = PerformanceEvaluator(sharpe_threshold=1.0)
        assert ev.sharpe_acceptable(scaling_session) is False

    def test_sharpe_acceptable_good(self, scaling_session):
        now = utcnow()
        # Create consistent positive returns for good Sharpe
        for i in range(20):
            scaling_session.add(ShadowResult(
                market_id=f'mkt-{i}',
                strategy_id='s1',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.5,
                accuracy=True,
                resolved_at=now - timedelta(hours=i),
                created_at=now,
            ))
        scaling_session.commit()

        ev = PerformanceEvaluator(sharpe_threshold=0.5)
        assert ev.sharpe_acceptable(scaling_session) is True

    def test_no_active_circuit_breakers(self, scaling_session):
        ev = PerformanceEvaluator()
        assert ev.no_active_circuit_breakers() is True

    def test_get_all_criteria(self, scaling_session):
        now = utcnow()
        for i in range(5):
            scaling_session.add(ShadowResult(
                market_id=f'mkt-{i}',
                strategy_id='s1',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.5,
                accuracy=True,
                resolved_at=now - timedelta(days=i),
                created_at=now,
            ))
        scaling_session.commit()

        ev = PerformanceEvaluator()
        criteria = ev.get_all_criteria(scaling_session)

        assert criteria['profitable_14d'] is True
        assert criteria['sharpe_ratio'] is not None
        assert criteria['circuit_breakers_active'] is False


class TestScalingManager:
    """Tests for ScalingManager."""

    def test_get_current_stage(self, scaling_session):
        from polyclaw.config import settings
        settings.shadow_stage = 2
        sm = ScalingManager()
        try:
            assert sm.get_current_stage() == 2
        finally:
            settings.shadow_stage = 0

    def test_evaluate_scale_empty_session(self):
        sm = ScalingManager()
        ready, reason = sm.evaluate_scale(None)
        assert ready is False
        assert 'database session' in reason.lower()

    def test_scale_to_invalid_stage(self, scaling_session):
        sm = ScalingManager()
        result = sm.scale_to(scaling_session, 99)
        assert result['success'] is False
        assert 'invalid stage' in result['reason'].lower()


class TestMarketExpander:
    """Tests for MarketExpander."""

    def test_suggest_expansion_empty(self, scaling_session):
        expander = MarketExpander()
        suggestions = expander.suggest_expansion(scaling_session)
        assert suggestions == []

    def test_suggest_expansion_candidates(self, scaling_session):
        # Add a market that meets expansion criteria
        now = utcnow()
        scaling_session.add(Market(
            market_id='expansion-candidate-1',
            title='High Liquidity Market',
            liquidity_usd=100_000,
            spread_bps=100,
            volume_24h_usd=20_000,
            category='politics',
            outcome_yes_price=0.55,
            outcome_no_price=0.45,
            is_active=True,
            fetched_at=now,
        ))
        # Add a market that doesn't meet criteria
        scaling_session.add(Market(
            market_id='low-liquidity-market',
            title='Low Liquidity Market',
            liquidity_usd=500,
            spread_bps=500,
            volume_24h_usd=100,
            category='novelty',
            outcome_yes_price=0.55,
            outcome_no_price=0.45,
            is_active=True,
            fetched_at=now,
        ))
        scaling_session.commit()

        expander = MarketExpander()
        suggestions = expander.suggest_expansion(scaling_session)

        assert len(suggestions) == 1
        assert suggestions[0].market_id == 'expansion-candidate-1'
        assert 'liquidity' in suggestions[0].reason.lower()

    def test_apply_expansion(self, scaling_session):
        now = utcnow()
        scaling_session.add(Market(
            market_id='new-market-1',
            title='New Market',
            liquidity_usd=80_000,
            spread_bps=80,
            volume_24h_usd=15_000,
            category='finance',
            outcome_yes_price=0.60,
            outcome_no_price=0.40,
            is_active=True,
            fetched_at=now,
        ))
        scaling_session.commit()

        expander = MarketExpander()
        result = expander.apply_expansion(scaling_session, 'new-market-1')

        assert result is True
        # Verify it's on the whitelist
        wl_ids = scaling_session.scalars(
            select(MarketWhitelistRecord.market_id)
        ).all()
        assert 'new-market-1' in wl_ids


class TestFeeCalculator:
    """Tests for FeeCalculator."""

    def test_calculate_platform_fee_amm(self):
        fc = FeeCalculator()
        fee = fc.calculate_platform_fee(100.0, venue='amm')
        assert fee == 0.0

    def test_calculate_platform_fee_orderbook(self):
        fc = FeeCalculator(fee_rate_orderbook=0.01)
        fee = fc.calculate_platform_fee(100.0, venue='orderbook')
        assert fee == 1.0

    def test_estimate_gas_fee(self):
        fc = FeeCalculator(eth_usd_price=3000.0)
        gas_fee = fc.estimate_gas_fee(100.0)
        # Expected: (30 gwei * 250000 gas / 1e9) * 3000 USD/ETH
        expected = (30.0 * 250000 / 1e9) * 3000
        assert gas_fee == pytest.approx(expected, rel=1e-3)

    def test_total_cost(self):
        fc = FeeCalculator(eth_usd_price=3000.0)
        spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.50,
            size=200.0,  # 200 shares => notional = 0.50 * 200.0 = $100
            market_id='test-market',
        )
        breakdown = fc.total_cost(spec, slippage_pct=0.01, venue='amm')

        assert isinstance(breakdown, FeeBreakdown)
        assert breakdown.platform_fee == 0.0
        assert breakdown.slippage_cost == pytest.approx(1.0, rel=1e-4)  # 1% of $100 notional
        assert breakdown.total_cost == pytest.approx(breakdown.gas_fee + breakdown.slippage_cost, rel=1e-4)

    def test_cost_effective_venue(self):
        fc = FeeCalculator(fee_rate_orderbook=0.01, eth_usd_price=3000.0)
        spec = OrderSpec(
            type=OrderType.LIMIT,
            side='yes',
            price=0.50,
            size=100.0,
            market_id='test-market',
        )
        venue = fc.cost_effective_venue(spec)
        assert venue in ('amm', 'orderbook')
