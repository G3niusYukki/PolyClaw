from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from polyclaw.db import Base
from polyclaw.domain import DecisionProposal, MarketSnapshot
from polyclaw.models import Position
from polyclaw.risk import RiskEngine
from polyclaw.timeutils import utcnow


def make_session():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_risk_rejects_stale_market_and_portfolio_exposure():
    session = make_session()
    session.add(Position(event_key='old', market_id='m-old', side='yes', notional_usd=240, avg_price=0.5, quantity=480, is_open=True))
    session.commit()

    market = MarketSnapshot(market_id='m1', title='demo', description='', yes_price=0.4, no_price=0.62, spread_bps=100, liquidity_usd=5000, volume_24h_usd=100, category='demo', event_key='e1', closes_at=None, fetched_at=utcnow() - timedelta(hours=4))
    proposal = DecisionProposal(side='yes', confidence=0.8, model_probability=0.55, market_implied_probability=0.4, edge_bps=1500, stake_usd=20, explanation='x', risk_flags=[])

    ok, flags = RiskEngine().evaluate(session, market, proposal)
    assert not ok
    assert 'stale_market_data' in flags
    assert 'portfolio_exposure_limit' in flags
