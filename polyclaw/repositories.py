from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.domain import DecisionProposal, EvidenceItem, MarketSnapshot
from polyclaw.models import Decision, Evidence, Market, Order, Position


def upsert_market(session: Session, market: MarketSnapshot) -> Market:
    record = session.scalar(select(Market).where(Market.market_id == market.market_id))
    if not record:
        record = Market(market_id=market.market_id, title=market.title, description=market.description, outcome_yes_price=market.yes_price, outcome_no_price=market.no_price, spread_bps=market.spread_bps, liquidity_usd=market.liquidity_usd, volume_24h_usd=market.volume_24h_usd, category=market.category, event_key=market.event_key, closes_at=market.closes_at, fetched_at=market.fetched_at, is_active=True)
        session.add(record)
    else:
        record.title = market.title
        record.description = market.description
        record.outcome_yes_price = market.yes_price
        record.outcome_no_price = market.no_price
        record.spread_bps = market.spread_bps
        record.liquidity_usd = market.liquidity_usd
        record.volume_24h_usd = market.volume_24h_usd
        record.category = market.category
        record.event_key = market.event_key
        record.closes_at = market.closes_at
        record.fetched_at = market.fetched_at
        record.is_active = True
    session.flush()
    return record


def replace_evidence(session: Session, market_record: Market, evidences: list[EvidenceItem]) -> None:
    market_record.evidences.clear()
    for item in evidences:
        market_record.evidences.append(Evidence(source=item.source, summary=item.summary, direction=item.direction, confidence=item.confidence, url=item.url, observed_at=item.observed_at))
    session.flush()


def create_decision(session: Session, market_record: Market, proposal: DecisionProposal, requires_approval: bool) -> Decision:
    decision = Decision(market_id_fk=market_record.id, side=proposal.side, confidence=proposal.confidence, model_probability=proposal.model_probability, market_implied_probability=proposal.market_implied_probability, edge_bps=proposal.edge_bps, stake_usd=proposal.stake_usd, status='proposed', explanation=proposal.explanation, risk_flags='|'.join(proposal.risk_flags), requires_approval=requires_approval)
    session.add(decision)
    session.flush()
    return decision


def record_order_and_position(session: Session, market_record: Market, decision: Decision, order_payload: dict) -> Order:
    order = Order(decision_id_fk=decision.id, client_order_id=order_payload['client_order_id'], mode=order_payload['mode'], side=order_payload['side'], price=order_payload['price'], size=order_payload['size'], notional_usd=order_payload['notional_usd'], status=order_payload['status'], venue_order_id=order_payload.get('venue_order_id', ''))
    session.add(order)
    position = Position(event_key=market_record.event_key, market_id=market_record.market_id, side=order_payload['side'], notional_usd=order_payload['notional_usd'], avg_price=order_payload['price'], quantity=order_payload['size'], is_open=True)
    session.add(position)
    decision.status = 'executed'
    session.flush()
    return order
