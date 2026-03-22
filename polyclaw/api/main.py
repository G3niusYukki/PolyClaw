from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.db import Base, engine, get_session
from polyclaw.models import AuditLog, Decision, Market, Position, ProposalRecord, ShadowResult

# Monitoring imports
from polyclaw.monitoring.health import HealthChecker as _HealthChecker
from polyclaw.monitoring.pnl import DailyReportGenerator, PnLReporter

# Reconciliation imports
from polyclaw.providers.ctf import PolymarketCTFProvider
from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider
from polyclaw.reconciliation.service import ReconciliationService
from polyclaw.safety import kill_switch_state, set_kill_switch
from polyclaw.schemas import (
    ApprovalResponse,
    DecisionOut,
    DiscrepancyItemOut,
    ProposalPreviewOut,
    ProposalRecordOut,
    RankedMarketOut,
    ReconciliationReportOut,
    ReconciliationRunResponse,
    RunnerTickResponse,
    ScanResponse,
)
from polyclaw.services.analysis import AnalysisService
from polyclaw.services.execution import ExecutionService
from polyclaw.services.runner import RunnerService
from polyclaw.shadow.accuracy import SignalAccuracyMonitor
from polyclaw.shadow.mode import ShadowModeEngine
from polyclaw.shadow.transition import LiveTransitionManager
from polyclaw.timeutils import utcnow
from polyclaw.workflow import ProposalWorkflowService

app = FastAPI(title='PolyClaw')
Base.metadata.create_all(bind=engine)
analysis_service = AnalysisService()
execution_service = ExecutionService()
runner_service = RunnerService()
workflow_service = ProposalWorkflowService()
shadow_mode_engine = ShadowModeEngine()
shadow_accuracy_monitor = SignalAccuracyMonitor()
live_transition_manager = LiveTransitionManager()

# Reconciliation providers (module-level singletons)
_ctf_provider = PolymarketCTFProvider()
_polymarket_api = PolymarketGammaProvider()

# In-memory store for the last reconciliation report (module-level)
_last_reconciliation_report = None


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'PolyClaw'}


@app.get('/health/detailed')
def health_detailed(session: Session = Depends(get_session)):
    """
    Return a detailed health status for all PolyClaw components.

    Checks: database connectivity, Polymarket API, CTF contract,
    data freshness, and kill switch status.
    """
    checker = _HealthChecker(session=session)
    status = checker.check()

    return {
        'overall_status': status.overall_status.value,
        'timestamp': status.timestamp.isoformat(),
        'checks': [
            {
                'component_name': c.component_name,
                'status': c.status.value,
                'latency_ms': round(c.latency_ms, 2),
                'error_message': c.error_message,
            }
            for c in status.checks
        ],
    }


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


@app.post('/proposals/persist', response_model=ScanResponse)
def persist_proposals(limit: int = 10, session: Session = Depends(get_session)):
    previews = analysis_service.proposal_previews(session, limit=limit)
    created = workflow_service.persist_previews(session, previews)
    session.commit()
    return ScanResponse(markets_scanned=len(previews), decisions_created=created)


@app.get('/proposal-records', response_model=list[ProposalRecordOut])
def proposal_records(session: Session = Depends(get_session)):
    rows = session.scalars(select(ProposalRecord).order_by(ProposalRecord.updated_at.desc())).all()
    return [
        ProposalRecordOut(
            id=row.id,
            market_id=row.market_id,
            title=row.title,
            suggested_side=row.suggested_side,
            confidence=row.confidence,
            edge_bps=row.edge_bps,
            suggested_stake_usd=row.suggested_stake_usd,
            ranking_reasons=[x for x in row.ranking_reasons.split('|') if x],
            evidence_summaries=[x for x in row.evidence_summaries.split('|') if x],
            risk_flags=[x for x in row.risk_flags.split('|') if x],
            status=row.status,
            explanation=row.explanation,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@app.post('/proposal-records/{proposal_id}/status', response_model=ProposalRecordOut)
def set_proposal_status(proposal_id: int, status: str, session: Session = Depends(get_session)):
    row = workflow_service.set_status(session, proposal_id, status)
    if not row:
        raise HTTPException(status_code=404, detail='proposal_not_found')
    return ProposalRecordOut(
        id=row.id,
        market_id=row.market_id,
        title=row.title,
        suggested_side=row.suggested_side,
        confidence=row.confidence,
        edge_bps=row.edge_bps,
        suggested_stake_usd=row.suggested_stake_usd,
        ranking_reasons=[x for x in row.ranking_reasons.split('|') if x],
        evidence_summaries=[x for x in row.evidence_summaries.split('|') if x],
        risk_flags=[x for x in row.risk_flags.split('|') if x],
        status=row.status,
        explanation=row.explanation,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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
    from polyclaw.repositories import create_decision, replace_evidence, upsert_market
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


# ---------------------------------------------------------------------------
# Shadow Mode Endpoints
# ---------------------------------------------------------------------------


@app.get('/shadow/results')
def shadow_results(window_days: int = 30, session: Session = Depends(get_session)):
    """List shadow trading results with accuracy data."""
    from datetime import timedelta

    from polyclaw.timeutils import utcnow

    cutoff = utcnow() - timedelta(days=window_days)
    rows = session.scalars(
        select(ShadowResult)
        .where(ShadowResult.created_at >= cutoff)
        .order_by(ShadowResult.created_at.desc())
    ).all()
    return [
        {
            'id': r.id,
            'market_id': r.market_id,
            'strategy_id': r.strategy_id,
            'predicted_side': r.predicted_side,
            'predicted_prob': r.predicted_prob,
            'shadow_fill_price': r.shadow_fill_price,
            'actual_outcome': r.actual_outcome,
            'pnl': r.pnl,
            'accuracy': r.accuracy,
            'resolved_at': r.resolved_at,
            'created_at': r.created_at,
        }
        for r in rows
    ]


@app.get('/shadow/accuracy')
def shadow_accuracy(window_days: int = 30, session: Session = Depends(get_session)):
    """Get signal accuracy report over a rolling window."""
    return shadow_accuracy_monitor.get_accuracy(window_days=window_days, session=session)


@app.post('/shadow/reset')
def shadow_reset(session: Session = Depends(get_session)):
    """Reset all shadow positions (mark them as closed)."""
    from polyclaw.safety import log_event

    # Close all open shadow positions
    shadow_positions = session.scalars(
        select(Position).where(Position.is_shadow.is_(True)).where(Position.is_open.is_(True))
    ).all()
    for pos in shadow_positions:
        pos.is_open = False

    log_event(session, 'shadow_reset', f'reset {len(shadow_positions)} shadow positions', 'ok')
    session.commit()
    return {'reset': len(shadow_positions), 'status': 'ok'}


@app.get('/shadow/positions')
def shadow_positions(session: Session = Depends(get_session)):
    """Get current shadow positions (open, in-memory)."""
    return session.scalars(
        select(Position)
        .where(Position.is_shadow.is_(True))
        .order_by(Position.opened_at.desc())
    ).all()


@app.get('/shadow/status')
def shadow_status(session: Session = Depends(get_session)):
    """Get shadow mode and transition status."""
    return live_transition_manager.get_status(session=session)


@app.get('/shadow/mode')
def shadow_mode():
    """Get current shadow mode enabled status."""
    return {'shadow_mode_enabled': settings.shadow_mode_enabled}


@app.post('/shadow/mode/{enabled}')
def set_shadow_mode(enabled: bool, session: Session = Depends(get_session)):
    """Enable or disable shadow mode."""
    from polyclaw.safety import log_event

    old_value = settings.shadow_mode_enabled
    settings.shadow_mode_enabled = enabled
    log_event(
        session,
        'shadow_mode_toggle',
        f'from={old_value}|to={enabled}',
        'ok',
    )
    session.commit()
    return {'shadow_mode_enabled': settings.shadow_mode_enabled}



# ---------------------------------------------------------------------------
# Reconciliation endpoints
# ---------------------------------------------------------------------------


@app.post('/reconciliation/run', response_model=ReconciliationRunResponse)
def run_reconciliation(session: Session = Depends(get_session)):
    """
    Trigger a full reconciliation run across system DB, Polymarket API, and CTF contract.

    Returns a summary of the reconciliation result including drift detection and
    auto-close actions.
    """
    service = ReconciliationService(
        session=session,
        ctf_provider=_ctf_provider,
        polymarket_api=_polymarket_api,
    )
    report = service.reconcile()

    # Store the report for retrieval via GET /reconciliation/report
    global _last_reconciliation_report
    _last_reconciliation_report = report

    return ReconciliationRunResponse(
        status='ok',
        drift_detected=report.drift_detected,
        total_drift_usd=report.total_drift_usd,
        discrepancy_count=len(report.discrepancy_items),
        auto_close_triggered=report.auto_close_triggered,
        auto_close_count=report.auto_close_count,
    )


@app.get('/reconciliation/report', response_model=ReconciliationReportOut)
def get_reconciliation_report(session: Session = Depends(get_session)):
    """
    Get the last reconciliation report.

    Returns 404 if no reconciliation has been run yet.
    """
    if _last_reconciliation_report is None:
        raise HTTPException(status_code=404, detail='no_reconciliation_report')
    report = _last_reconciliation_report
    return ReconciliationReportOut(
        drift_detected=report.drift_detected,
        total_drift_usd=report.total_drift_usd,
        discrepancy_items=[
            DiscrepancyItemOut(
                market_id=item.market_id,
                source1=item.source1,
                source2=item.source2,
                expected_value=item.expected_value,
                actual_value=item.actual_value,
                drift_usd=item.drift_usd,
            )
            for item in report.discrepancy_items
        ],
        timestamp=report.timestamp,
        auto_close_triggered=report.auto_close_triggered,
        auto_close_count=report.auto_close_count,
    )


# ---------------------------------------------------------------------------
# PnL / Reports Endpoints
# ---------------------------------------------------------------------------


_pnl_reporter = PnLReporter()
_daily_report_generator = DailyReportGenerator(pnl_reporter=_pnl_reporter)


@app.get('/reports/pnl')
def pnl_report(
    date: str | None = None,
    session: Session = Depends(get_session),
):
    """
    Get daily PnL breakdown by strategy, market, and side.

    Query params:
        date: ISO date string (YYYY-MM-DD), defaults to today
    """
    target = utcnow()
    if date:
        from datetime import datetime as dt
        try:
            target = dt.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail='Invalid date format. Use YYYY-MM-DD.')

    report = _pnl_reporter.daily_pnl(session, date=target)
    return report


@app.get('/reports/attribution')
def attribution_report(
    start_date: str,
    end_date: str,
    session: Session = Depends(get_session),
):
    """
    Get strategy attribution over a date range.

    Query params:
        start_date: ISO datetime string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end_date: ISO datetime string
    """
    from datetime import datetime as dt

    try:
        start = dt.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid start_date format.')

    try:
        end = dt.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid end_date format.')

    if start >= end:
        raise HTTPException(status_code=400, detail='start_date must be before end_date.')

    report = _pnl_reporter.attribution(session, start, end)
    return report


@app.get('/reports/daily')
def daily_report(
    date: str | None = None,
    session: Session = Depends(get_session),
):
    """
    Get the full daily report with PnL summary, metrics, and top positions.

    Query params:
        date: ISO date string (YYYY-MM-DD), defaults to today
    """
    target = utcnow()
    if date:
        from datetime import datetime as dt
        try:
            target = dt.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail='Invalid date format. Use YYYY-MM-DD.')

    report = _daily_report_generator.generate(session, date=target)
    return {
        'date': report.date,
        'pnl_summary': {
            'total_pnl': report.pnl_summary.total_pnl,
            'trade_count': report.pnl_summary.trade_count,
            'win_count': report.pnl_summary.win_count,
            'loss_count': report.pnl_summary.loss_count,
            'win_rate': report.pnl_summary.win_rate,
            'sharpe_ratio': report.pnl_summary.sharpe_ratio,
        },
        'top_positions': report.top_positions,
        'unrealized_pnl': report.unrealized_pnl,
    }


# ---------------------------------------------------------------------------
# Order Management Endpoints
# ---------------------------------------------------------------------------


@app.get('/orders/{order_id}')
def get_order(order_id: int, session: Session = Depends(get_session)):
    """Get a specific order by ID."""
    from polyclaw.models import Order
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail='order_not_found')
    return {
        'id': order.id,
        'client_order_id': order.client_order_id,
        'venue_order_id': order.venue_order_id,
        'side': order.side,
        'price': order.price,
        'size': order.size,
        'notional_usd': order.notional_usd,
        'status': order.status,
        'mode': order.mode,
        'retry_count': getattr(order, 'retry_count', 0),
        'status_history': getattr(order, 'status_history', []),
        'submitted_at': order.submitted_at,
        'updated_at': getattr(order, 'updated_at', None),
    }


@app.get('/orders')
def list_orders(
    status: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """List recent orders with optional status filter."""
    from polyclaw.models import Order
    stmt = select(Order).order_by(Order.submitted_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Order.status == status)
    rows = session.scalars(stmt).all()
    return [
        {
            'id': order.id,
            'client_order_id': order.client_order_id,
            'venue_order_id': order.venue_order_id,
            'side': order.side,
            'price': order.price,
            'size': order.size,
            'notional_usd': order.notional_usd,
            'status': order.status,
            'mode': order.mode,
            'retry_count': getattr(order, 'retry_count', 0),
            'submitted_at': order.submitted_at,
            'updated_at': getattr(order, 'updated_at', None),
        }
        for order in rows
    ]
