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


class RankedMarketOut(BaseModel):
    market_id: str
    title: str
    score: float
    reasons: list[str]
    liquidity_usd: float
    volume_24h_usd: float
    spread_bps: int


class ProposalPreviewOut(BaseModel):
    market_id: str
    title: str
    rank_score: float
    ranking_reasons: list[str]
    evidence_summaries: list[str]
    suggested_side: str
    confidence: float
    model_probability: float
    market_implied_probability: float
    edge_bps: int
    suggested_stake_usd: float
    explanation: str
    risk_flags: list[str]
    should_trade: bool


class ProposalRecordOut(BaseModel):
    id: int
    market_id: str
    title: str
    suggested_side: str
    confidence: float
    edge_bps: int
    suggested_stake_usd: float
    ranking_reasons: list[str]
    evidence_summaries: list[str]
    risk_flags: list[str]
    status: str
    explanation: str
    created_at: datetime
    updated_at: datetime


class DiscrepancyItemOut(BaseModel):
    market_id: str
    source1: str
    source2: str
    expected_value: float
    actual_value: float
    drift_usd: float


class ReconciliationReportOut(BaseModel):
    drift_detected: bool
    total_drift_usd: float
    discrepancy_items: list[DiscrepancyItemOut]
    timestamp: datetime
    auto_close_triggered: bool
    auto_close_count: int


class ReconciliationRunResponse(BaseModel):
    status: str
    drift_detected: bool
    total_drift_usd: float
    discrepancy_count: int
    auto_close_triggered: bool
    auto_close_count: int
