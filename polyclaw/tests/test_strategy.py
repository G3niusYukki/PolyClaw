from polyclaw.domain import DecisionProposal, EvidenceItem, MarketSnapshot
from polyclaw.strategies.base import BaseStrategy, Side, Signal
from polyclaw.timeutils import utcnow


class _TestStrategy(BaseStrategy):
    """Minimal strategy for testing score_market-like behaviour."""

    @property
    def strategy_id(self) -> str:
        return 'test_heuristic'

    @property
    def name(self) -> str:
        return 'Test Heuristic'

    @property
    def version(self) -> str:
        return '0.1.0'

    def compute_features(self, market: MarketSnapshot) -> dict:
        return {}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Replicate the old StrategyEngine.score_market logic as a strategy."""
        evidences = features.get('_evidences', [])
        yes_strength = sum(e.confidence for e in evidences if e.direction == 'yes')
        no_strength = sum(e.confidence for e in evidences if e.direction == 'no')
        neutral = sum(e.confidence for e in evidences if e.direction == 'neutral')

        total = yes_strength + no_strength + neutral
        if total <= 0:
            return None

        raw_probability = 0.5 + ((yes_strength - no_strength) / max(total, 1e-6)) * 0.25
        model_probability = min(max(raw_probability, 0.03), 0.97)

        if model_probability >= market.yes_price:
            side = Side.YES
            implied = market.yes_price
            edge = int((model_probability - implied) * 10000)
        else:
            side = Side.NO
            implied = market.no_price
            edge = int(((1 - model_probability) - implied) * 10000)

        confidence = min(0.95, 0.45 + abs(yes_strength - no_strength) / max(total, 1e-6) * 0.5)

        if confidence < 0.5 or edge < 100:
            return None

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=confidence,
            edge_bps=edge,
            explanation=f'Model probability={model_probability:.3f}; market yes={market.yes_price:.3f}',
            market_id=market.market_id,
            model_probability=model_probability,
            market_implied_probability=implied,
        )


def _score_market(market: MarketSnapshot, evidences: list[EvidenceItem]) -> DecisionProposal | None:
    """Bridge: replicate old StrategyEngine.score_market using a test strategy."""
    strategy = _TestStrategy()
    signal = strategy.generate_signals(market, {'_evidences': evidences})
    if signal is None:
        return None

    stake = min(50, 10 + signal.edge_bps / 100)
    return DecisionProposal(
        side=signal.side.value,
        confidence=signal.confidence,
        model_probability=signal.model_probability,
        market_implied_probability=signal.market_implied_probability,
        edge_bps=signal.edge_bps,
        stake_usd=round(stake, 2),
        explanation=signal.explanation,
        risk_flags=[],
    )


def test_strategy_produces_yes_decision_for_strong_yes_evidence():
    market = MarketSnapshot(market_id='m1', title='demo', description='', yes_price=0.35, no_price=0.68, spread_bps=100, liquidity_usd=2000, volume_24h_usd=100, category='demo', event_key='e1', closes_at=None, fetched_at=utcnow())
    evidences = [
        EvidenceItem(source='a', summary='x', direction='yes', confidence=0.8),
        EvidenceItem(source='b', summary='x', direction='yes', confidence=0.7),
        EvidenceItem(source='c', summary='x', direction='no', confidence=0.3),
    ]
    proposal = _score_market(market, evidences)
    assert proposal is not None
    assert proposal.side == 'yes'
    assert proposal.edge_bps > 0
