from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.db import Base, engine, get_session
from polyclaw.models import Decision, Market, Position, AuditLog
from polyclaw.schemas import ApprovalResponse, DecisionOut, RunnerTickResponse, ScanResponse
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
