from dataclasses import dataclass

from polyclaw.domain import EvidenceItem, MarketSnapshot


@dataclass
class ProposalPreview:
    market: MarketSnapshot
    rank_score: float
    ranking_reasons: list[str]
    evidences: list[EvidenceItem]
    suggested_side: str
    confidence: float
    model_probability: float
    market_implied_probability: float
    edge_bps: int
    suggested_stake_usd: float
    explanation: str
    risk_flags: list[str]
    should_trade: bool
