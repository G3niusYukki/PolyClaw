"""Tests for shadow mode infrastructure (Week 8.1)."""

from datetime import timedelta

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.models import Position, ShadowResult
from polyclaw.shadow.mode import ShadowModeEngine, ShadowPosition, process_shadow_signals
from polyclaw.strategies.base import Side, Signal
from polyclaw.timeutils import utcnow


class TestShadowPosition:
    def test_shadow_position_to_dict(self):
        """ShadowPosition dataclass serializes correctly."""
        now = utcnow()
        pos = ShadowPosition(
            market_id='market-1',
            side='yes',
            quantity=100.0,
            entry_price=0.55,
            shadow_fill_price=0.515,
            shadow_fill_time=now,
            status='open',
            strategy_id='test-strategy',
            pnl=0.0,
        )
        d = pos.to_dict()
        assert d['market_id'] == 'market-1'
        assert d['side'] == 'yes'
        assert d['quantity'] == 100.0
        assert d['entry_price'] == 0.55
        assert d['shadow_fill_price'] == 0.515
        assert d['status'] == 'open'
        assert d['strategy_id'] == 'test-strategy'
        assert d['pnl'] == 0.0


class TestShadowModeEngine:
    def test_get_mid_price(self, sample_market):
        """ShadowModeEngine calculates mid price correctly."""
        engine = ShadowModeEngine()
        mid = engine.get_mid_price(sample_market)
        assert mid == round((0.55 + 0.48) / 2, 4)  # (yes + no) / 2

    def test_calculate_shadow_fill_price_yes(self, sample_market):
        """Shadow fill price uses mid price for yes side."""
        engine = ShadowModeEngine()
        fill = engine.calculate_shadow_fill_price(sample_market, 'yes')
        expected = round((0.55 + 0.48) / 2, 4)
        assert fill == expected

    def test_calculate_shadow_fill_price_no(self, sample_market):
        """Shadow fill price uses mid price for no side."""
        engine = ShadowModeEngine()
        fill = engine.calculate_shadow_fill_price(sample_market, 'no')
        expected = round((0.55 + 0.48) / 2, 4)
        assert fill == expected

    def test_calculate_pnl_yes_win(self, sample_market):
        """PnL calculated correctly for YES position that wins."""
        engine = ShadowModeEngine()
        shadow_pos = ShadowPosition(
            market_id='market-1',
            side='yes',
            quantity=100.0,
            entry_price=0.55,
            shadow_fill_price=0.515,
            shadow_fill_time=utcnow(),
        )
        # Outcome: YES resolved at 1.0
        pnl = engine.calculate_pnl(shadow_pos, 1.0)
        assert pnl == round((1.0 - 0.515) * 100.0, 4)

    def test_calculate_pnl_no_win(self, sample_market):
        """PnL calculated correctly for NO position that wins."""
        engine = ShadowModeEngine()
        shadow_pos = ShadowPosition(
            market_id='market-1',
            side='no',
            quantity=100.0,
            entry_price=0.45,
            shadow_fill_price=0.485,
            shadow_fill_time=utcnow(),
        )
        # Outcome: YES at 1.0, NO at 0.0
        pnl = engine.calculate_pnl(shadow_pos, 0.0)
        assert pnl == round((0.485 - 0.0) * 100.0, 4)

    def test_calculate_pnl_no_loss(self, sample_market):
        """PnL calculated correctly for NO position that loses."""
        engine = ShadowModeEngine()
        shadow_pos = ShadowPosition(
            market_id='market-1',
            side='no',
            quantity=100.0,
            entry_price=0.45,
            shadow_fill_price=0.485,
            shadow_fill_time=utcnow(),
        )
        # Outcome: YES at 1.0
        pnl = engine.calculate_pnl(shadow_pos, 1.0)
        assert pnl < 0  # Loss

    def test_resolve_position(self, sample_market):
        """resolve_position marks position as resolved and calculates PnL."""
        engine = ShadowModeEngine()
        shadow_pos = ShadowPosition(
            market_id='market-1',
            side='yes',
            quantity=100.0,
            entry_price=0.55,
            shadow_fill_price=0.515,
            shadow_fill_time=utcnow(),
            status='open',
        )
        engine.add_position(shadow_pos)

        resolved = engine.resolve_position('market-1', 1.0)
        assert resolved is not None
        assert resolved.status == 'resolved'
        assert resolved.market_id == 'market-1'

    def test_resolve_position_not_found(self):
        """resolve_position returns None for unknown market."""
        engine = ShadowModeEngine()
        resolved = engine.resolve_position('unknown-market', 1.0)
        assert resolved is None

    def test_reset_clears_positions(self, sample_market):
        """reset() clears all shadow positions."""
        engine = ShadowModeEngine()
        shadow_pos = ShadowPosition(
            market_id='market-1',
            side='yes',
            quantity=100.0,
            entry_price=0.55,
            shadow_fill_price=0.515,
            shadow_fill_time=utcnow(),
        )
        engine.add_position(shadow_pos)
        assert len(engine.positions) == 1

        engine.reset()
        assert len(engine.positions) == 0


class TestProcessShadowSignals:
    def test_process_shadow_signals_creates_positions(self, db_session, sample_market):
        """process_shadow_signals creates shadow positions in DB."""
        signals = [
            Signal(
                strategy_id='event_catalyst',
                side=Side.YES,
                confidence=0.70,
                edge_bps=800,
                explanation='strong signal',
                market_id='test-market-1',
                model_probability=0.65,
                market_implied_probability=0.55,
                stake_usd=10.0,
            )
        ]
        market_data = [sample_market]

        created = process_shadow_signals(signals, market_data, db_session)

        assert len(created) == 1
        assert created[0].market_id == 'test-market-1'
        assert created[0].side == 'yes'
        assert created[0].strategy_id == 'event_catalyst'

    def test_process_shadow_signals_no_matching_market(self, db_session):
        """process_shadow_signals skips signals with no matching market."""
        signals = [
            Signal(
                strategy_id='event_catalyst',
                side=Side.YES,
                confidence=0.70,
                edge_bps=800,
                explanation='strong signal',
                market_id='unknown-market',
                stake_usd=10.0,
            )
        ]

        created = process_shadow_signals(signals, [], db_session)
        assert len(created) == 0

    def test_process_shadow_signals_creates_db_records(self, db_session, sample_market):
        """Shadow positions and results are persisted to DB."""
        signals = [
            Signal(
                strategy_id='test-strategy',
                side=Side.YES,
                confidence=0.75,
                edge_bps=900,
                explanation='test',
                market_id='test-market-1',
                stake_usd=20.0,
            )
        ]

        process_shadow_signals(signals, [sample_market], db_session)

        # Check DB records
        positions = db_session.query(Position).filter(Position.is_shadow.is_(True)).all()
        assert len(positions) == 1
        assert positions[0].market_id == 'test-market-1'
        assert positions[0].is_shadow is True

        results = db_session.query(ShadowResult).all()
        assert len(results) == 1
        assert results[0].strategy_id == 'test-strategy'
        assert results[0].predicted_side == 'yes'
        assert results[0].actual_outcome == ''  # Not resolved yet


class TestShadowModeToggle:
    def test_shadow_mode_disabled_uses_real_execution(self, db_session):
        """When shadow_mode_enabled=False, ExecutionService uses real path."""
        from polyclaw.domain import DecisionProposal
        from polyclaw.repositories import upsert_market

        # Create a market and decision
        market = upsert_market(
            db_session,
            MarketSnapshot(
                market_id='toggle-test',
                title='Test Market',
                description='',
                yes_price=0.60,
                no_price=0.42,
                spread_bps=120,
                liquidity_usd=50000,
                volume_24h_usd=10000,
                category='test',
                event_key='toggle-1',
                closes_at=utcnow() + timedelta(days=5),
                fetched_at=utcnow(),
            ),
        )

        proposal = DecisionProposal(
            side='yes',
            confidence=0.70,
            model_probability=0.68,
            market_implied_probability=0.60,
            edge_bps=800,
            stake_usd=10.0,
            explanation='test',
            risk_flags=[],
        )

        from polyclaw.repositories import create_decision
        decision = create_decision(db_session, market, proposal, requires_approval=False)

        # Disable shadow mode
        original = settings.shadow_mode_enabled
        settings.shadow_mode_enabled = False

        try:
            from polyclaw.services.execution import ExecutionService
            svc = ExecutionService()
            considered, submitted = svc.process_ready_decisions(db_session)

            # Real execution should have created an Order record
            from polyclaw.models import Order
            orders = db_session.query(Order).all()
            assert len(orders) == 1
            assert orders[0].mode == 'paper'  # Still paper since execution_mode is paper
        finally:
            settings.shadow_mode_enabled = original

    def test_shadow_mode_enabled_uses_shadow_path(self, db_session, sample_market):
        """When shadow_mode_enabled=True, ExecutionService uses shadow path."""
        from polyclaw.domain import DecisionProposal
        from polyclaw.repositories import upsert_market

        market = upsert_market(db_session, sample_market)

        proposal = DecisionProposal(
            side='yes',
            confidence=0.70,
            model_probability=0.68,
            market_implied_probability=sample_market.yes_price,
            edge_bps=800,
            stake_usd=10.0,
            explanation='test',
            risk_flags=[],
        )

        from polyclaw.repositories import create_decision
        decision = create_decision(db_session, market, proposal, requires_approval=False)

        # Ensure shadow mode is enabled
        original = settings.shadow_mode_enabled
        settings.shadow_mode_enabled = True

        try:
            from polyclaw.services.execution import ExecutionService
            svc = ExecutionService()
            considered, submitted = svc.process_ready_decisions(db_session)

            # Shadow execution should have created a shadow position
            positions = db_session.query(Position).filter(Position.is_shadow.is_(True)).all()
            assert len(positions) >= 1
            shadow_pos = next((p for p in positions if p.market_id == sample_market.market_id), None)
            assert shadow_pos is not None
            assert shadow_pos.is_shadow is True
        finally:
            settings.shadow_mode_enabled = original
