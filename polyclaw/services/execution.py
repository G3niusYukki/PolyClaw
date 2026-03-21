from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.models import Decision, Market
from polyclaw.providers.paper_execution import PaperExecutionProvider
from polyclaw.repositories import record_order_and_position
from polyclaw.safety import daily_executed_notional, kill_switch_state, log_event
from polyclaw.timeutils import utcnow


class ExecutionService:
    def __init__(self):
        self.executor = PaperExecutionProvider()

    def process_ready_decisions(self, session: Session) -> tuple[int, int]:
        if kill_switch_state(session)['enabled']:
            log_event(session, 'execution_skip', 'kill switch enabled', 'blocked')
            session.commit()
            return 0, 0

        stmt = select(Decision, Market).join(Market, Decision.market_id_fk == Market.id).where(Decision.status == 'proposed')
        rows = session.execute(stmt).all()
        considered = len(rows)
        submitted = 0
        failures = 0
        daily_notional = daily_executed_notional(session)

        for decision, market in rows:
            if decision.requires_approval and settings.require_approval:
                continue
            if daily_notional + decision.stake_usd > settings.max_daily_loss_usd:
                log_event(session, 'execution_skip', f'daily cap exceeded for decision={decision.id}', 'blocked')
                continue
            try:
                price = market.outcome_yes_price if decision.side == 'yes' else market.outcome_no_price
                payload = self.executor.submit_order(market, decision.side, decision.stake_usd, price)
                record_order_and_position(session, market, decision, payload)
                daily_notional += decision.stake_usd
                submitted += 1
                log_event(session, 'order_submitted', f'decision={decision.id}|market={market.market_id}|side={decision.side}', 'ok')
            except Exception as exc:
                failures += 1
                log_event(session, 'order_failed', f'decision={decision.id}|error={exc}', 'error')
                if failures >= settings.max_consecutive_failures:
                    log_event(session, 'kill_switch', 'consecutive execution failures', 'enabled')
                    break
        session.commit()
        return considered, submitted

    def approve(self, session: Session, decision_id: int) -> Decision | None:
        decision = session.get(Decision, decision_id)
        if not decision:
            return None
        decision.requires_approval = False
        decision.approved_at = utcnow()
        session.commit()
        session.refresh(decision)
        return decision
