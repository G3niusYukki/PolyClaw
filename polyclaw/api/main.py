from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.db import Base, engine, get_session
from polyclaw.models import Decision, Market, Position, AuditLog
from polyclaw.schemas import ApprovalResponse, DecisionOut, ProposalPreviewOut, RankedMarketOut, RunnerTickResponse, ScanResponse
from polyclaw.services.analysis import AnalysisService
from polyclaw.safety import kill_switch_state, set_kill_switch
from polyclaw.services.execution import ExecutionService
from polyclaw.services.runner import RunnerService

app = FastAPI(title='PolyClaw')
Base.metadata.create_all(bind=engine)
analysis_service = AnalysisService()
execution_service = ExecutionService()
runner_service = RunnerService()


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'PolyClaw'}


@app.post('/scan', response_model=ScanResponse)
def scan(session: Session = Depends(get_session)):
    markets_scanned, decisions_created = analysis_service.scan(session)
    return ScanResponse(markets_scanned=markets_scanned, decisions_created=decisions_created)


@app.get('/markets')
def list_markets(session: Session = Depends(get_session)):
    return session.scalars(select(Market).order_by(Market.fetched_at.desc())).all()


@app.get('/candidates', response_model=list[RankedMarketOut])
def candidates(limit: int = 10):
    ranked = analysis_service.ranked_candidates(limit=limit)
    return [
        RankedMarketOut(
            market_id=item.market.market_id,
            title=item.market.title,
            score=item.score,
            reasons=item.reasons,
            liquidity_usd=item.market.liquidity_usd,
            volume_24h_usd=item.market.volume_24h_usd,
            spread_bps=item.market.spread_bps,
        )
        for item in ranked
    ]


@app.get('/proposals', response_model=list[ProposalPreviewOut])
def proposals(limit: int = 10, session: Session = Depends(get_session)):
    previews = analysis_service.proposal_previews(session, limit=limit)
    return [
        ProposalPreviewOut(
            market_id=item.market.market_id,
            title=item.market.title,
            rank_score=item.rank_score,
            ranking_reasons=item.ranking_reasons,
            evidence_summaries=[e.summary for e in item.evidences],
            suggested_side=item.suggested_side,
            confidence=item.confidence,
            model_probability=item.model_probability,
            market_implied_probability=item.market_implied_probability,
            edge_bps=item.edge_bps,
            suggested_stake_usd=item.suggested_stake_usd,
            explanation=item.explanation,
            risk_flags=item.risk_flags,
            should_trade=item.should_trade,
        )
        for item in previews
    ]


@app.get('/decisions', response_model=list[DecisionOut])
def list_decisions(session: Session = Depends(get_session)):
    rows = session.execute(select(Decision, Market.title).join(Market, Decision.market_id_fk == Market.id).order_by(Decision.created_at.desc())).all()
    return [
        DecisionOut(
            id=decision.id,
            market_title=title,
            side=decision.side,
            confidence=decision.confidence,
            model_probability=decision.model_probability,
            market_implied_probability=decision.market_implied_probability,
            edge_bps=decision.edge_bps,
            stake_usd=decision.stake_usd,
            status=decision.status,
            explanation=decision.explanation,
            risk_flags=[x for x in decision.risk_flags.split('|') if x],
            requires_approval=decision.requires_approval,
            created_at=decision.created_at,
        )
        for decision, title in rows
    ]


@app.post('/proposals/{market_id}/materialize', response_model=ScanResponse)
def materialize_proposal(market_id: str, session: Session = Depends(get_session)):
    previews = analysis_service.proposal_previews(session, limit=settings.scan_limit)
    match = next((p for p in previews if p.market.market_id == market_id and p.should_trade), None)
    if not match:
        raise HTTPException(status_code=404, detail='tradable_proposal_not_found')
    from polyclaw.domain import DecisionProposal
    from polyclaw.repositories import upsert_market, replace_evidence, create_decision
    market_record = next((m for m in session.scalars(select(Market).where(Market.market_id == market_id)).all()), None)
    if market_record is None:
        market_record = upsert_market(session, match.market)
    replace_evidence(session, market_record, match.evidences)
    proposal = DecisionProposal(
        side=match.suggested_side,
        confidence=match.confidence,
        model_probability=match.model_probability,
        market_implied_probability=match.market_implied_probability,
        edge_bps=match.edge_bps,
        stake_usd=match.suggested_stake_usd,
        explanation=match.explanation,
        risk_flags=match.risk_flags,
    )
    create_decision(session, market_record, proposal, requires_approval=settings.require_approval)
    session.commit()
    return ScanResponse(markets_scanned=1, decisions_created=1)


@app.post('/decisions/{decision_id}/approve', response_model=ApprovalResponse)
def approve(decision_id: int, session: Session = Depends(get_session)):
    decision = execution_service.approve(session, decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail='decision_not_found')
    return ApprovalResponse(decision_id=decision.id, status='approved')


@app.post('/runner/tick')
def runner_tick(session: Session = Depends(get_session)):
    return runner_service.tick(session)


@app.post('/execute-ready', response_model=RunnerTickResponse)
def execute_ready(session: Session = Depends(get_session)):
    considered, submitted = execution_service.process_ready_decisions(session)
    return RunnerTickResponse(decisions_considered=considered, orders_submitted=submitted)


@app.get('/positions')
def positions(session: Session = Depends(get_session)):
    return session.scalars(select(Position).order_by(Position.opened_at.desc())).all()


@app.get('/audit-logs')
def audit_logs(session: Session = Depends(get_session)):
    return session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).all()


@app.get('/kill-switch')
def get_kill_switch(session: Session = Depends(get_session)):
    return kill_switch_state(session)


@app.post('/kill-switch/enable')
def enable_kill_switch(reason: str = 'manual stop', session: Session = Depends(get_session)):
    return set_kill_switch(session, True, reason)


@app.post('/kill-switch/disable')
def disable_kill_switch(reason: str = 'manual resume', session: Session = Depends(get_session)):
    return set_kill_switch(session, False, reason)
