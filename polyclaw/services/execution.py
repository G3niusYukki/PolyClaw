from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.models import Decision, Market
from polyclaw.providers.paper_execution import PaperExecutionProvider
from polyclaw.repositories import record_order_and_position
from polyclaw.timeutils import utcnow


class ExecutionService:
    def __init__(self):
        self.executor = PaperExecutionProvider()

    def process_ready_decisions(self, session: Session) -> tuple[int, int]:
        stmt = select(Decision, Market).join(Market, Decision.market_id_fk == Market.id).where(Decision.status == 'proposed')
        rows = session.execute(stmt).all()
        considered = len(rows)
        submitted = 0
        for decision, market in rows:
            if decision.requires_approval and settings.require_approval:
                continue
            price = market.outcome_yes_price if decision.side == 'yes' else market.outcome_no_price
            payload = self.executor.submit_order(market, decision.side, decision.stake_usd, price)
            record_order_and_position(session, market, decision, payload)
            submitted += 1
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
