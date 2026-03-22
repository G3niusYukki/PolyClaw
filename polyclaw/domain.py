from dataclasses import dataclass, field
from datetime import datetime

from polyclaw.timeutils import utcnow


@dataclass
class MarketSnapshot:
    market_id: str
    title: str
    description: str
    yes_price: float
    no_price: float
    spread_bps: int
    liquidity_usd: float
    volume_24h_usd: float
    category: str
    event_key: str
    closes_at: datetime | None
    fetched_at: datetime


@dataclass
class EvidenceItem:
    source: str
    summary: str
    direction: str
    confidence: float
    url: str = ''
    observed_at: datetime = field(default_factory=utcnow)


@dataclass
class OrderBookLevel:
    price: float
    size: float
    side: str  # 'bid' or 'ask'


@dataclass
class OrderBookSnapshot:
    market_id: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    spread: float
    mid_price: float
    fetched_at: datetime


@dataclass
class Trade:
    market_id: str
    trade_id: str
    side: str  # 'yes' or 'no'
    price: float
    size: float
    timestamp: datetime
    taker_side: str  # 'buy' or 'sell'


@dataclass
class DecisionProposal:
    side: str
    confidence: float
    model_probability: float
    market_implied_probability: float
    edge_bps: int
    stake_usd: float
    explanation: str
    risk_flags: list[str]
