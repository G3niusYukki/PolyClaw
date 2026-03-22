"""Tests for PnL attribution and reporting."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from polyclaw.db import Base
from polyclaw.models import ShadowResult
from polyclaw.monitoring.pnl import DailyReportGenerator, PnLReporter
from polyclaw.timeutils import utcnow


@pytest.fixture
def pnl_session():
    """Create a fresh in-memory SQLite database for PnL tests."""
    engine = create_engine('sqlite:///:memory:', future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class TestPnLReporter:
    """Tests for PnLReporter daily_pnl, attribution, and equity_curve."""

    def test_daily_pnl_empty(self, pnl_session):
        """Empty database returns zero PnL."""
        reporter = PnLReporter()
        result = reporter.daily_pnl(pnl_session)
        assert result['total_pnl'] == 0.0
        assert result['trade_count'] == 0
        assert result['by_strategy'] == {}
        assert result['by_market'] == {}

    def test_daily_pnl_with_results(self, pnl_session):
        """Daily PnL aggregates resolved shadow results."""
        now = utcnow()
        results = [
            ShadowResult(
                market_id='mkt-1',
                strategy_id='strategy_a',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='yes',
                pnl=0.50,
                accuracy=True,
                resolved_at=now,
                created_at=now,
            ),
            ShadowResult(
                market_id='mkt-2',
                strategy_id='strategy_a',
                predicted_side='no',
                predicted_prob=0.35,
                shadow_fill_price=0.40,
                actual_outcome='no',
                pnl=0.60,
                accuracy=True,
                resolved_at=now,
                created_at=now,
            ),
            ShadowResult(
                market_id='mkt-3',
                strategy_id='strategy_b',
                predicted_side='yes',
                predicted_prob=0.70,
                shadow_fill_price=0.55,
                actual_outcome='no',
                pnl=-0.55,
                accuracy=False,
                resolved_at=now,
                created_at=now,
            ),
        ]
        for r in results:
            pnl_session.add(r)
        pnl_session.commit()

        reporter = PnLReporter()
        result = reporter.daily_pnl(pnl_session)

        assert result['trade_count'] == 3
        assert result['total_pnl'] == pytest.approx(0.50 + 0.60 - 0.55, rel=1e-4)
        assert result['by_strategy']['strategy_a'] == pytest.approx(1.10, rel=1e-4)
        assert result['by_strategy']['strategy_b'] == pytest.approx(-0.55, rel=1e-4)
        assert result['by_side']['yes'] == pytest.approx(-0.05, rel=1e-4)
        assert result['by_side']['no'] == pytest.approx(0.60, rel=1e-4)

    def test_attribution(self, pnl_session):
        """Attribution groups PnL by strategy over date range."""
        now = utcnow()
        pnl_session.add(ShadowResult(
            market_id='mkt-1',
            strategy_id='event_catalyst',
            predicted_side='yes',
            predicted_prob=0.70,
            shadow_fill_price=0.60,
            actual_outcome='yes',
            pnl=0.40,
            accuracy=True,
            resolved_at=now,
            created_at=now,
        ))
        pnl_session.commit()

        reporter = PnLReporter()
        result = reporter.attribution(
            pnl_session,
            start_date=now - timedelta(days=7),
            end_date=now + timedelta(days=1),
        )

        assert 'event_catalyst' in result['strategies']
        assert result['strategies']['event_catalyst']['trades'] == 1
        assert result['strategies']['event_catalyst']['wins'] == 1
        assert result['strategies']['event_catalyst']['win_rate'] == 1.0

    def test_equity_curve(self, pnl_session):
        """Equity curve tracks cumulative equity and drawdown."""
        now = utcnow()

        # Add results on day 1
        pnl_session.add(ShadowResult(
            market_id='mkt-1',
            strategy_id='s1',
            predicted_side='yes',
            predicted_prob=0.65,
            shadow_fill_price=0.50,
            actual_outcome='yes',
            pnl=1.0,
            accuracy=True,
            resolved_at=now - timedelta(days=2),
            created_at=now - timedelta(days=2),
        ))
        # Add result on day 2
        pnl_session.add(ShadowResult(
            market_id='mkt-2',
            strategy_id='s1',
            predicted_side='no',
            predicted_prob=0.40,
            shadow_fill_price=0.40,
            actual_outcome='no',
            pnl=0.60,
            accuracy=True,
            resolved_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        ))
        # Add losing result on day 3
        pnl_session.add(ShadowResult(
            market_id='mkt-3',
            strategy_id='s1',
            predicted_side='yes',
            predicted_prob=0.70,
            shadow_fill_price=0.60,
            actual_outcome='no',
            pnl=-0.60,
            accuracy=False,
            resolved_at=now,
            created_at=now,
        ))
        pnl_session.commit()

        reporter = PnLReporter()
        curve = reporter.equity_curve(pnl_session, days=7)

        assert len(curve) == 3
        # Day 1: equity = 1.0, drawdown = 0
        assert curve[0]['equity_usd'] == pytest.approx(1.0, rel=1e-4)
        assert curve[0]['drawdown_pct'] == 0.0
        # Day 2: equity = 1.6, drawdown = 0
        assert curve[1]['equity_usd'] == pytest.approx(1.6, rel=1e-4)
        # Day 3: equity = 1.0, drawdown = (1.6 - 1.0) / 1.6 * 100
        assert curve[2]['equity_usd'] == pytest.approx(1.0, rel=1e-4)
        assert curve[2]['drawdown_pct'] > 0


class TestDailyReportGenerator:
    """Tests for DailyReportGenerator."""

    def test_generate_empty(self, pnl_session):
        """Generate report with no data returns zeroed metrics."""
        gen = DailyReportGenerator()
        report = gen.generate(pnl_session)
        assert report.pnl_summary.total_pnl == 0.0
        assert report.pnl_summary.trade_count == 0
        assert report.pnl_summary.win_rate == 0.0
        assert report.sharpe_ratio is None

    def test_generate_with_trades(self, pnl_session):
        """Generate report with trades computes correct metrics."""
        now = utcnow()
        for i in range(5):
            pnl_session.add(ShadowResult(
                market_id=f'mkt-{i}',
                strategy_id='test_strategy',
                predicted_side='yes',
                predicted_prob=0.65,
                shadow_fill_price=0.50,
                actual_outcome='yes' if i < 3 else 'no',
                pnl=0.50 if i < 3 else -0.50,
                accuracy=i < 3,
                resolved_at=now,
                created_at=now,
            ))
        pnl_session.commit()

        gen = DailyReportGenerator()
        report = gen.generate(pnl_session)

        assert report.pnl_summary.trade_count == 5
        assert report.pnl_summary.win_count == 3
        assert report.pnl_summary.loss_count == 2
        assert report.pnl_summary.win_rate == pytest.approx(0.6, rel=1e-2)

    def test_send_telegram_not_configured(self, pnl_session):
        """Telegram send returns failure when not configured."""
        gen = DailyReportGenerator()
        pnl_session.add(ShadowResult(
            market_id='m1',
            strategy_id='s1',
            predicted_side='yes',
            predicted_prob=0.65,
            shadow_fill_price=0.50,
            actual_outcome='yes',
            pnl=1.0,
            accuracy=True,
            resolved_at=utcnow(),
            created_at=utcnow(),
        ))
        pnl_session.commit()

        report = gen.generate(pnl_session)
        response = gen.send_telegram(report)
        assert response.success is False
        assert 'not configured' in response.error.lower()
