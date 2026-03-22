"""Tests for signal accuracy monitoring (Week 8.2)."""

from datetime import timedelta

import pytest

from polyclaw.models import Position, ShadowResult
from polyclaw.shadow.accuracy import SignalAccuracyMonitor, ShadowResultRecord
from polyclaw.timeutils import utcnow


class TestSignalAccuracyMonitor:
    def test_update_resolves_shadow_result(self, db_session):
        """update() marks shadow result as resolved with outcome and accuracy."""
        now = utcnow()
        result = ShadowResult(
            market_id='test-market-1',
            strategy_id='test-strategy',
            predicted_side='yes',
            predicted_prob=0.75,
            shadow_fill_price=0.50,
            actual_outcome='',
            pnl=0.0,
            accuracy=False,
            resolved_at=None,
            created_at=now - timedelta(hours=2),
        )
        db_session.add(result)
        db_session.commit()

        monitor = SignalAccuracyMonitor()
        record = monitor.update('test-market-1', 'yes', 'yes', db_session)

        assert record is not None
        assert record.actual_outcome == 'yes'
        assert record.accuracy is True
        assert record.resolved_at is not None

    def test_update_incorrect_prediction(self, db_session):
        """update() marks accuracy=False when prediction is wrong."""
        now = utcnow()
        result = ShadowResult(
            market_id='test-market-2',
            strategy_id='test-strategy',
            predicted_side='no',
            predicted_prob=0.60,
            shadow_fill_price=0.50,
            actual_outcome='',
            pnl=0.0,
            accuracy=False,
            resolved_at=None,
            created_at=now - timedelta(hours=1),
        )
        db_session.add(result)
        db_session.commit()

        monitor = SignalAccuracyMonitor()
        record = monitor.update('test-market-2', 'no', 'yes', db_session)

        assert record is not None
        assert record.accuracy is False

    def test_update_no_matching_result(self, db_session):
        """update() returns None when no matching shadow result exists."""
        monitor = SignalAccuracyMonitor()
        record = monitor.update('nonexistent-market', 'yes', 'yes', db_session)
        assert record is None

    def test_update_also_closes_shadow_position(self, db_session):
        """update() marks the corresponding shadow position as closed."""
        now = utcnow()
        result = ShadowResult(
            market_id='test-market-3',
            strategy_id='test-strategy',
            predicted_side='yes',
            predicted_prob=0.70,
            shadow_fill_price=0.50,
            actual_outcome='',
            pnl=0.0,
            accuracy=False,
            resolved_at=None,
            created_at=now - timedelta(hours=1),
        )
        db_session.add(result)

        position = Position(
            market_id='test-market-3',
            event_key='test-event',
            side='yes',
            notional_usd=10.0,
            avg_price=0.50,
            quantity=20.0,
            is_open=True,
            is_shadow=True,
        )
        db_session.add(position)
        db_session.commit()

        monitor = SignalAccuracyMonitor()
        monitor.update('test-market-3', 'yes', 'yes', db_session)

        db_session.expire(position)
        assert position.is_open is False

    def test_get_accuracy_empty(self, db_session):
        """get_accuracy() returns zero values when no data."""
        monitor = SignalAccuracyMonitor()
        accuracy = monitor.get_accuracy(window_days=30, session=db_session)

        assert accuracy['accuracy'] == 0.0
        assert accuracy['total_signals'] == 0
        assert accuracy['correct_signals'] == 0
        assert accuracy['by_strategy'] == {}
        assert accuracy['total_pnl'] == 0.0

    def test_get_accuracy_with_results(self, db_session):
        """get_accuracy() calculates correct metrics from resolved results."""
        now = utcnow()

        # Create 4 resolved results: 3 correct, 1 wrong
        correct_results = [
            ShadowResult(
                market_id=f'market-{i}',
                strategy_id='test-strategy',
                predicted_side='yes',
                predicted_prob=0.70,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.5,
                accuracy=True,
                resolved_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i + 1),
            )
            for i in range(1, 4)
        ]
        wrong_result = ShadowResult(
            market_id='market-wrong',
            strategy_id='test-strategy',
            predicted_side='no',
            predicted_prob=0.60,
            shadow_fill_price=0.40,
            actual_outcome='yes',
            pnl=-0.4,
            accuracy=False,
            resolved_at=now - timedelta(hours=5),
            created_at=now - timedelta(hours=6),
        )

        for r in correct_results:
            db_session.add(r)
        db_session.add(wrong_result)
        db_session.commit()

        monitor = SignalAccuracyMonitor()
        accuracy = monitor.get_accuracy(window_days=30, session=db_session)

        assert accuracy['total_signals'] == 4
        assert accuracy['correct_signals'] == 3
        assert accuracy['accuracy'] == 0.75
        assert 'test-strategy' in accuracy['by_strategy']
        assert accuracy['by_strategy']['test-strategy'] == 0.75

    def test_get_accuracy_no_session(self):
        """get_accuracy() returns zeros when no session provided."""
        monitor = SignalAccuracyMonitor()
        accuracy = monitor.get_accuracy(window_days=30, session=None)

        assert accuracy['accuracy'] == 0.0
        assert accuracy['total_signals'] == 0

    def test_get_accuracy_by_strategy(self, db_session):
        """get_accuracy() aggregates per-strategy correctly."""
        now = utcnow()

        # Strategy A: 2 correct out of 2
        for i in range(2):
            r = ShadowResult(
                market_id=f'market-a-{i}',
                strategy_id='strategy-a',
                predicted_side='yes',
                predicted_prob=0.70,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.5,
                accuracy=True,
                resolved_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i + 1),
            )
            db_session.add(r)

        # Strategy B: 1 correct out of 2
        r_b1 = ShadowResult(
            market_id='market-b-1',
            strategy_id='strategy-b',
            predicted_side='yes',
            predicted_prob=0.65,
            shadow_fill_price=0.50,
            actual_outcome='yes',
            pnl=0.5,
            accuracy=True,
            resolved_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
        )
        r_b2 = ShadowResult(
            market_id='market-b-2',
            strategy_id='strategy-b',
            predicted_side='no',
            predicted_prob=0.60,
            shadow_fill_price=0.40,
            actual_outcome='yes',
            pnl=-0.4,
            accuracy=False,
            resolved_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=3),
        )
        db_session.add(r_b1)
        db_session.add(r_b2)
        db_session.commit()

        monitor = SignalAccuracyMonitor()
        accuracy = monitor.get_accuracy(window_days=30, session=db_session)

        assert accuracy['by_strategy']['strategy-a'] == 1.0
        assert accuracy['by_strategy']['strategy-b'] == 0.5
