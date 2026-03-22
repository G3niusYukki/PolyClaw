"""Tests for staged position sizing (Week 9.1)."""


from polyclaw.config import settings
from polyclaw.execution.staged_size import StagedPositionSizer, TradingStage
from polyclaw.models import ShadowResult, TradingStageRecord
from polyclaw.timeutils import utcnow


class TestTradingStage:
    def test_stage_scale_factors(self):
        """Each stage has the correct scale factor."""
        assert TradingStage.SHADOW.scale_factor == 0.0
        assert TradingStage.STAGE1_10PCT.scale_factor == 0.10
        assert TradingStage.STAGE2_25PCT.scale_factor == 0.25
        assert TradingStage.STAGE3_50PCT.scale_factor == 0.50
        assert TradingStage.STAGE4_100PCT.scale_factor == 1.0

    def test_stage_display_names(self):
        """Each stage has a human-readable display name."""
        assert TradingStage.SHADOW.display_name == 'SHADOW'
        assert TradingStage.STAGE1_10PCT.display_name == 'STAGE1_10PCT'
        assert TradingStage.STAGE2_25PCT.display_name == 'STAGE2_25PCT'


class TestStagedPositionSizer:
    def test_get_stage_from_config(self, db_session):
        """get_stage() returns the stage from settings."""
        settings.shadow_stage = 2
        sizer = StagedPositionSizer()
        assert sizer.get_stage() == TradingStage.STAGE2_25PCT
        settings.shadow_stage = 0  # reset

    def test_get_stage_invalid_value(self, db_session):
        """get_stage() returns SHADOW for invalid config value."""
        settings.shadow_stage = 99
        sizer = StagedPositionSizer()
        assert sizer.get_stage() == TradingStage.SHADOW
        settings.shadow_stage = 0  # reset

    def test_scale_stake_shadow(self, db_session):
        """scale_stake() returns 0 for SHADOW stage."""
        settings.shadow_stage = 0
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(100.0) == 0.0
        settings.shadow_stage = 0  # reset

    def test_scale_stake_stage1(self, db_session):
        """scale_stake() returns 10% for STAGE1."""
        settings.shadow_stage = 1
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(100.0) == 10.0
        settings.shadow_stage = 0  # reset

    def test_scale_stake_stage2(self, db_session):
        """scale_stake() returns 25% for STAGE2."""
        settings.shadow_stage = 2
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(100.0) == 25.0
        settings.shadow_stage = 0  # reset

    def test_scale_stake_stage3(self, db_session):
        """scale_stake() returns 50% for STAGE3."""
        settings.shadow_stage = 3
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(100.0) == 50.0
        settings.shadow_stage = 0  # reset

    def test_scale_stake_stage4(self, db_session):
        """scale_stake() returns 100% for STAGE4."""
        settings.shadow_stage = 4
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(100.0) == 100.0
        settings.shadow_stage = 0  # reset

    def test_scale_stake_rounding(self, db_session):
        """scale_stake() rounds to 2 decimal places."""
        settings.shadow_stage = 2
        sizer = StagedPositionSizer()
        assert sizer.scale_stake(33.33) == 8.33  # 25% of 33.33 = 8.3325, rounded to 8.33
        settings.shadow_stage = 0  # reset

    def test_can_advance_no_session(self, db_session):
        """can_advance() returns False when no session provided."""
        sizer = StagedPositionSizer()
        can_advance, reasons = sizer.can_advance(session=None)
        assert can_advance is False

    def test_can_advance_at_max_stage(self, db_session):
        """can_advance() returns False when already at max stage."""
        settings.shadow_stage = 4
        sizer = StagedPositionSizer()
        can_advance, reasons = sizer.can_advance(session=db_session)
        assert can_advance is False
        assert 'maximum stage' in reasons[0]
        settings.shadow_stage = 0  # reset

    def test_advance_records_stage_change(self, db_session):
        """advance() records the stage change in DB."""
        # Add enough data for gates to pass
        from datetime import timedelta
        now = utcnow()

        # Add 51 shadow results
        for i in range(51):
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

        settings.shadow_stage = 0
        sizer = StagedPositionSizer()
        result = sizer.advance(db_session)

        assert result.success is True
        assert result.new_stage == 1

        # Verify stage record was created
        records = db_session.query(TradingStageRecord).all()
        assert len(records) == 1
        assert records[0].stage == 1

        settings.shadow_stage = 0  # reset

    def test_rollback_to_shadow(self, db_session):
        """rollback() reverts to shadow mode and records the change."""
        settings.shadow_stage = 3
        sizer = StagedPositionSizer()
        result = sizer.rollback(db_session)

        assert result.success is True
        assert result.new_stage == 0
        assert settings.shadow_stage == 0

        # Verify stage record was created
        records = db_session.query(TradingStageRecord).all()
        assert len(records) == 1
        assert records[0].stage == 0

        settings.shadow_stage = 0  # reset
