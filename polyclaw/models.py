from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id_fk: Mapped[int] = mapped_column(ForeignKey('decisions.id'))
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default='paper')
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    size: Mapped[float] = mapped_column(Float)
    notional_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default='submitted')
    venue_order_id: Mapped[str] = mapped_column(String(128), default='')
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
