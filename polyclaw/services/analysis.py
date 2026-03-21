from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.evidence import HeuristicEvidenceEngine
from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider
from polyclaw.providers.sample_market import SampleMarketProvider
from polyclaw.ranking import MarketRanker
from polyclaw.repositories import create_decision, replace_evidence, upsert_market
from polyclaw.risk import RiskEngine
from polyclaw.safety import log_event
from polyclaw.strategy import StrategyEngine


class AnalysisService:
    def __init__(self):
        if settings.market_source == 'polymarket':
            self.market_provider = PolymarketGammaProvider()
        else:
            self.market_provider = SampleMarketProvider()
        self.evidence_engine = HeuristicEvidenceEngine()
        self.ranker = MarketRanker()
        self.strategy = StrategyEngine()
        self.risk = RiskEngine()

    def scan(self, session: Session) -> tuple[int, int]:
        try:
            markets = self.market_provider.list_markets(limit=settings.scan_limit)
            log_event(session, 'market_fetch', f'source={settings.market_source}|count={len(markets)}', 'ok')
        except Exception as exc:
            log_event(session, 'market_fetch', f'source={settings.market_source}|error={exc}', 'error')
            session.commit()
            if settings.market_source == 'polymarket':
                markets = SampleMarketProvider().list_markets(limit=settings.scan_limit)
                log_event(session, 'market_fetch_fallback', f'source=sample|count={len(markets)}', 'ok')
            else:
                raise

        ranked_markets = self.ranker.rank(markets, limit=settings.scan_limit)
        created = 0
        for ranked_market in ranked_markets:
            market = ranked_market.market
            market_record = upsert_market(session, market)
            evidences = self.evidence_engine.build(ranked_market)
            replace_evidence(session, market_record, evidences)
            proposal = self.strategy.score_market(market, evidences)
            if not proposal:
                continue
            ok, flags = self.risk.evaluate(session, market, proposal)
            proposal.risk_flags = flags
            if not ok:
                log_event(session, 'decision_rejected', f'market={market.market_id}|flags={"|".join(flags)}', 'blocked')
                continue
            create_decision(session, market_record, proposal, requires_approval=settings.require_approval)
            log_event(session, 'decision_created', f'market={market.market_id}|side={proposal.side}|edge_bps={proposal.edge_bps}|rank_score={ranked_market.score}', 'ok')
            created += 1
        session.commit()
        return len(ranked_markets), created

    def ranked_candidates(self, limit: int | None = None):
        try:
            markets = self.market_provider.list_markets(limit=settings.scan_limit)
        except Exception:
            markets = SampleMarketProvider().list_markets(limit=settings.scan_limit)
        ranked = self.ranker.rank(markets, limit=limit or settings.scan_limit)
        return ranked
