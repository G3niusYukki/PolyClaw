from datetime import datetime
from pydantic import BaseModel


class ScanResponse(BaseModel):
    markets_scanned: int
    decisions_created: int


class DecisionOut(BaseModel):
    id: int
    market_title: str
    side: str
    confidence: float
    model_probability: float
    market_implied_probability: float
    edge_bps: int
    stake_usd: float
    status: str
    explanation: str
    risk_flags: list[str]
    requires_approval: bool
    created_at: datetime


class ApprovalResponse(BaseModel):
    decision_id: int
    status: str


class RunnerTickResponse(BaseModel):
    decisions_considered: int
    orders_submitted: int
