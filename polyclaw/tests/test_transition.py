"""Tests for live transition manager (Week 9.4)."""

from datetime import timedelta

from polyclaw.models import ShadowResult
from polyclaw.shadow.transition import LiveTransitionManager
from polyclaw.timeutils import utcnow


class TestLiveTransitionManager:
    def test_can_go_live_fails_with_no_data(self, db_session):
        """can_go_live() fails when no shadow results exist."""
        mgr = LiveTransitionManager()
        can_live, reasons = mgr.can_go_live(db_session)

        assert can_live is False
        assert len(reasons) > 0
        # Should fail on accuracy gate and trades gate
        reason_text = ' '.join(reasons)
        assert 'signal_accuracy' in reason_text or 'shadow_trades' in reason_text

    def test_can_go_live_fails_with_insufficient_accuracy(self, db_session):
        """can_go_live() fails when accuracy is below 60%."""
        now = utcnow()
        # Create 101 resolved results with 50% accuracy
        for i in range(101):
            r = ShadowResult(
                market_id=f'market-{i}',
                strategy_id='test',
                predicted_side='yes',
                predicted_prob=0.60,
                shadow_fill_price=0.50,
                actual_outcome='yes' if i < 50 else 'no',  # 50% accuracy
                pnl=0.0,
                accuracy=(i < 50),
                resolved_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i + 1),
            )
            db_session.add(r)
        db_session.commit()

        mgr = LiveTransitionManager()
        can_live, reasons = mgr.can_go_live(db_session)

        assert can_live is False
        reason_text = ' '.join(reasons)
        assert 'accuracy' in reason_text

    def test_can_go_live_fails_with_insufficient_trades(self, db_session):
        """can_go_live() fails when shadow trades are <= 100."""
        now = utcnow()
        # Create 50 results (below 100 threshold)
        for i in range(50):
            r = ShadowResult(
                market_id=f'market-{i}',
                strategy_id='test',
                predicted_side='yes',
                predicted_prob=0.75,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.5,
                accuracy=True,
                resolved_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i + 1),
            )
            db_session.add(r)
        db_session.commit()

        mgr = LiveTransitionManager()
        can_live, reasons = mgr.can_go_live(db_session)

        assert can_live is False
        reason_text = ' '.join(reasons)
        assert 'shadow_trades' in reason_text

    def test_can_go_live_passes_with_all_gates_met(self, db_session):
        """can_go_live() passes when all gate criteria are met."""
        now = utcnow()
        # Create 101 resolved results with 70% accuracy (> 60%)
        for i in range(101):
            r = ShadowResult(
                market_id=f'market-{i}',
                strategy_id='test',
                predicted_side='yes',
                predicted_prob=0.75,
                shadow_fill_price=0.50,
                actual_outcome='yes' if i < 70 else 'no',
                pnl=0.5 if i < 70 else -0.5,
                accuracy=(i < 70),
                resolved_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i + 1),
            )
            db_session.add(r)
        db_session.commit()

        mgr = LiveTransitionManager()
        can_live, reasons = mgr.can_go_live(db_session)

        assert can_live is True
        assert reasons == []

    def test_trigger_live_sets_flag(self, db_session):
        """trigger_live() enables live trading and logs the transition."""
        mgr = LiveTransitionManager()
        assert mgr.live_enabled is False

        result = mgr.trigger_live(db_session)
        assert result is True
        assert mgr.live_enabled is True

    def test_rollback_disables_live(self, db_session):
        """rollback() disables live trading and reverts to shadow."""
        mgr = LiveTransitionManager()
        mgr.trigger_live(db_session)
        assert mgr.live_enabled is True

        result = mgr.rollback(db_session)
        assert result is True
        assert mgr.live_enabled is False

    def test_rollback_creates_stage_record(self, db_session):
        """rollback() creates a TradingStageRecord."""
        from polyclaw.models import TradingStageRecord

        mgr = LiveTransitionManager()
        mgr.trigger_live(db_session)
        mgr.rollback(db_session)

        records = db_session.query(TradingStageRecord).all()
        assert len(records) == 1
        assert records[0].stage == 0

    def test_get_status_returns_dict(self, db_session):
        """get_status() returns a complete status dict."""
        mgr = LiveTransitionManager()
        status = mgr.get_status(session=db_session)

        assert 'mode' in status
        assert 'current_stage' in status
        assert 'live_enabled' in status
        assert 'gate_status' in status
        assert 'all_gates_passed' in status
        assert 'blocking_reasons' in status

    def test_get_status_no_session(self):
        """get_status() returns minimal status when no session provided."""
        mgr = LiveTransitionManager()
        status = mgr.get_status(session=None)

        assert status['mode'] == 'shadow'
        assert status['live_enabled'] is False
