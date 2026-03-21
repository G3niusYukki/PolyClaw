from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.services.analysis import AnalysisService
from polyclaw.services.execution import ExecutionService


class RunnerService:
    def __init__(self):
        self.analysis = AnalysisService()
        self.execution = ExecutionService()

    def tick(self, session: Session) -> dict:
        markets_scanned, decisions_created = self.analysis.scan(session)
        orders_submitted = 0
        decisions_considered = 0
        if settings.auto_execute:
            decisions_considered, orders_submitted = self.execution.process_ready_decisions(session)
        return {
            'markets_scanned': markets_scanned,
            'decisions_created': decisions_created,
            'decisions_considered': decisions_considered,
            'orders_submitted': orders_submitted,
        }
