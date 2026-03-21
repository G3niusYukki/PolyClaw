from sqlalchemy import select, func
from sqlalchemy.orm import Session

from polyclaw.models import AuditLog, Decision, Order
from polyclaw.timeutils import utcnow


def log_event(session: Session, action: str, payload: str, result: str = "ok") -> AuditLog:
    row = AuditLog(action=action, payload=payload, result=result)
    session.add(row)
    session.flush()
    return row


def kill_switch_state(session: Session) -> dict:
    row = session.scalar(select(AuditLog).where(AuditLog.action == 'kill_switch').order_by(AuditLog.created_at.desc()))
    if not row:
        return {'enabled': False, 'reason': ''}
    enabled = row.result == 'enabled'
    return {'enabled': enabled, 'reason': row.payload}


def set_kill_switch(session: Session, enabled: bool, reason: str = '') -> dict:
    log_event(session, 'kill_switch', reason, 'enabled' if enabled else 'disabled')
    session.commit()
    return {'enabled': enabled, 'reason': reason}


def daily_executed_notional(session: Session) -> float:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(select(func.coalesce(func.sum(Order.notional_usd), 0.0)).where(Order.submitted_at >= start))
    return float(total or 0.0)


def open_proposed_count(session: Session) -> int:
    total = session.scalar(select(func.count(Decision.id)).where(Decision.status == 'proposed'))
    return int(total or 0)
