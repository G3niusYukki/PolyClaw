from polyclaw.domain import EvidenceItem, MarketSnapshot
from polyclaw.strategy import StrategyEngine
from polyclaw.timeutils import utcnow


def test_strategy_produces_yes_decision_for_strong_yes_evidence():
    engine = StrategyEngine()
    market = MarketSnapshot(market_id='m1', title='demo', description='', yes_price=0.35, no_price=0.68, spread_bps=100, liquidity_usd=2000, volume_24h_usd=100, category='demo', event_key='e1', closes_at=None, fetched_at=utcnow())
    evidences = [
        EvidenceItem(source='a', summary='x', direction='yes', confidence=0.8),
        EvidenceItem(source='b', summary='x', direction='yes', confidence=0.7),
        EvidenceItem(source='c', summary='x', direction='no', confidence=0.3),
    ]
    proposal = engine.score_market(market, evidences)
    assert proposal is not None
    assert proposal.side == 'yes'
    assert proposal.edge_bps > 0
