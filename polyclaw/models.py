from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from polyclaw.db import Base
from polyclaw.timeutils import utcnow


class Market(Base):
    __tablename__ = 'markets'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default='')
    outcome_yes_price: Mapped[float] = mapped_column(Float)
    outcome_no_price: Mapped[float] = mapped_column(Float)
    spread_bps: Mapped[int] = mapped_column(Integer, default=0)
    liquidity_usd: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h_usd: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(128), default='general')
    event_key: Mapped[str] = mapped_column(String(256), default='')
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    evidences: Mapped[list['Evidence']] = relationship(back_populates='market', cascade='all, delete-orphan')
    decisions: Mapped[list['Decision']] = relationship(back_populates='market', cascade='all, delete-orphan')


class Evidence(Base):
    __tablename__ = 'evidences'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id_fk: Mapped[int] = mapped_column(ForeignKey('markets.id'))
    source: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    url: Mapped[str] = mapped_column(String(512), default='')
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    market: Mapped['Market'] = relationship(back_populates='evidences')


class Decision(Base):
    __tablename__ = 'decisions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id_fk: Mapped[int] = mapped_column(ForeignKey('markets.id'))
    side: Mapped[str] = mapped_column(String(8))
    confidence: Mapped[float] = mapped_column(Float)
    model_probability: Mapped[float] = mapped_column(Float)
    market_implied_probability: Mapped[float] = mapped_column(Float)
    edge_bps: Mapped[int] = mapped_column(Integer)
    stake_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default='proposed')
    explanation: Mapped[str] = mapped_column(Text)
    risk_flags: Mapped[str] = mapped_column(Text, default='')
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    market: Mapped['Market'] = relationship(back_populates='decisions')
    orders: Mapped[list['Order']] = relationship(back_populates='decision', cascade='all, delete-orphan')


class Order(Base):
    __tablename__ = 'orders'

    # Order state constants
    STATUS_CREATED = 'created'
    STATUS_SUBMITTED = 'submitted'
    STATUS_ACKNOWLEDGED = 'acknowledged'
    STATUS_PARTIAL_FILL = 'partial_fill'
    STATUS_FILLED = 'filled'
    STATUS_CANCELING = 'canceling'
    STATUS_CANCELED = 'canceled'
    STATUS_REJECTED = 'rejected'
    STATUS_FAILED = 'failed'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id_fk: Mapped[int | None] = mapped_column(ForeignKey('decisions.id'), default=None)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default='paper')
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    notional_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default='submitted')
    venue_order_id: Mapped[str] = mapped_column(String(128), default='')
    status_history: Mapped[list | None] = mapped_column(JSON, default=list)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    decision: Mapped['Decision'] = relationship(back_populates='orders')


class Position(Base):
    __tablename__ = 'positions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(256), index=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    side: Mapped[str] = mapped_column(String(8))
    notional_usd: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    is_shadow: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    strategy_id: Mapped[str] = mapped_column(String(128), default='', index=True)


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[str] = mapped_column(String(64), default='ok')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ProposalRecord(Base):
    __tablename__ = 'proposal_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    suggested_side: Mapped[str] = mapped_column(String(16), default='hold')
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    edge_bps: Mapped[int] = mapped_column(Integer, default=0)
    suggested_stake_usd: Mapped[float] = mapped_column(Float, default=0.0)
    explanation: Mapped[str] = mapped_column(Text, default='')
    ranking_reasons: Mapped[str] = mapped_column(Text, default='')
    evidence_summaries: Mapped[str] = mapped_column(Text, default='')
    risk_flags: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(32), default='new', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ShadowResult(Base):
    __tablename__ = 'shadow_results'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    strategy_id: Mapped[str] = mapped_column(String(128), index=True)
    predicted_side: Mapped[str] = mapped_column(String(8))
    predicted_prob: Mapped[float] = mapped_column(Float)
    shadow_fill_price: Mapped[float] = mapped_column(Float)
    actual_outcome: Mapped[str] = mapped_column(String(8), default='')
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class TradingStageRecord(Base):
    __tablename__ = 'trading_stage_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(256), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LLMEstimate(Base):
    __tablename__ = 'llm_estimates'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id_fk: Mapped[int] = mapped_column(ForeignKey('markets.id'))
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    estimated_probability_yes: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text, default='')
    key_factors: Mapped[str] = mapped_column(Text, default='')
    model: Mapped[str] = mapped_column(String(128), default='')
    provider: Mapped[str] = mapped_column(String(64), default='')
    raw_response: Mapped[str] = mapped_column(Text, default='')
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    market: Mapped['Market'] = relationship()


class NewsArticleRecord(Base):
    __tablename__ = 'news_articles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id_fk: Mapped[int] = mapped_column(ForeignKey('markets.id'))
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512))
    snippet: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(128), default='')
    url: Mapped[str] = mapped_column(String(512), default='')
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    market: Mapped['Market'] = relationship()


class SentimentScore(Base):
    __tablename__ = 'sentiment_scores'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    magnitude: Mapped[float] = mapped_column(Float)
    adjusted_probability: Mapped[float] = mapped_column(Float)
    articles_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    key_insights: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalletTracking(Base):
    __tablename__ = 'wallet_tracking'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), default='')
    is_profitable: Mapped[bool] = mapped_column(Boolean, default=False)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OnChainPosition(Base):
    __tablename__ = 'onchain_positions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    wallet_address: Mapped[str] = mapped_column(String(128), index=True)
    side: Mapped[str] = mapped_column(String(8))
    size_usd: Mapped[float] = mapped_column(Float)
    outcome_tokens: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SmartMoneySignal(Base):
    __tablename__ = 'smart_money_signals'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    signal_type: Mapped[str] = mapped_column(String(32))  # whale_position, tracked_wallet, unusual_activity
    direction: Mapped[str] = mapped_column(String(8))
    magnitude: Mapped[float] = mapped_column(Float)
    details: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CrossPlatformPriceRecord(Base):
    __tablename__ = 'cross_platform_prices'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    probability_yes: Mapped[float] = mapped_column(Float)
    volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    url: Mapped[str] = mapped_column(String(512), default='')
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ArbitrageOpportunity(Base):
    __tablename__ = 'arbitrage_opportunities'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), index=True)
    discrepancy_bps: Mapped[int] = mapped_column(Integer)
    polymarket_price: Mapped[float] = mapped_column(Float)
    consensus_price: Mapped[float] = mapped_column(Float)
    platforms_agreeing: Mapped[int] = mapped_column(Integer)
    platform_list: Mapped[str] = mapped_column(String(256), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MarketWhitelistRecord(Base):
    __tablename__ = 'market_whitelist'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    added_reason: Mapped[str] = mapped_column(String(256), default='')
