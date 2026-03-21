from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.providers.sample_evidence import SampleEvidenceProvider
from polyclaw.providers.sample_market import SampleMarketProvider
from polyclaw.repositories import create_decision, replace_evidence, upsert_market
from polyclaw.risk import RiskEngine
from polyclaw.strategy import StrategyEngine


class AnalysisService:
    def __init__(self):
        self.market_provider = SampleMarketProvider()
        self.evidence_provider = SampleEvidenceProvider()
        self.strategy = StrategyEngine()
        self.risk = RiskEngine()

    def scan(self, session: Session) -> tuple[int, int]:
        markets = self.market_provider.list_markets(limit=settings.scan_limit)
        created = 0
        for market in markets:
            market_record = upsert_market(session, market)
            evidences = self.evidence_provider.gather(market)
            replace_evidence(session, market_record, evidences)
            proposal = self.strategy.score_market(market, evidences)
            if not proposal:
                continue
            ok, flags = self.risk.evaluate(session, market, proposal)
            proposal.risk_flags = flags
            if not ok:
                continue
            create_decision(session, market_record, proposal, requires_approval=settings.require_approval)
            created += 1
        session.commit()
        return len(markets), created
