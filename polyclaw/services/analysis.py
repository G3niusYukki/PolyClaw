from sqlalchemy.orm import Session

from polyclaw.config import settings
from polyclaw.evidence import HeuristicEvidenceEngine
from polyclaw.proposals import ProposalPreview
from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider
from polyclaw.providers.sample_market import SampleMarketProvider
from polyclaw.ranking import MarketRanker
from polyclaw.repositories import create_decision, replace_evidence, upsert_market
from polyclaw.risk import RiskEngine
from polyclaw.safety import log_event
from polyclaw.strategy import StrategyEngine
from polyclaw.strategies import FeatureEngine
from polyclaw.strategies.registry import StrategyRegistry


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
        self.feature_engine = FeatureEngine()
        self._registry = StrategyRegistry()

    def _get_enabled_strategies(self) -> list:
        """Get enabled strategies from registry. Returns empty list if none registered."""
        return self._registry.list_enabled()

    def _generate_multi_strategy_proposals(self, market, evidences: list):
        """Generate proposals from all enabled strategies.

        Returns a list of proposals from each strategy that produces a signal.
        Falls back to the legacy StrategyEngine if no strategies are registered.
        """
        strategies = self._get_enabled_strategies()

        if not strategies:
            # Backward compatibility: use legacy strategy engine
            proposal = self.strategy.score_market(market, evidences)
            return [proposal] if proposal else []

        proposals = []
        features_by_strategy = self.feature_engine.compute_features(market, strategies)

        for strat in strategies:
            features = features_by_strategy.get(strat.strategy_id, {})
            signal = strat.generate_signals(market, features)
            if signal is not None:
                # Convert Signal to DecisionProposal for compatibility
                from polyclaw.domain import DecisionProposal
                stake = min(settings.max_position_usd, 10 + signal.edge_bps / 100)
                proposals.append(
                    DecisionProposal(
                        side=signal.side.value,
                        confidence=signal.confidence,
                        model_probability=(
                            market.yes_price if signal.side.value == 'yes'
                            else (1 - market.no_price)
                        ),
                        market_implied_probability=(
                            market.yes_price if signal.side.value == 'yes'
                            else market.no_price
                        ),
                        edge_bps=signal.edge_bps,
                        stake_usd=round(stake, 2),
                        explanation=signal.explanation,
                        risk_flags=[],
                    )
                )
        return proposals

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
            proposals = self._generate_multi_strategy_proposals(market, evidences)
            for proposal in proposals:
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

    def proposal_previews(self, session: Session, limit: int | None = None) -> list[ProposalPreview]:
        previews: list[ProposalPreview] = []
        for ranked_market in self.ranked_candidates(limit=limit or settings.scan_limit):
            market = ranked_market.market
            evidences = self.evidence_engine.build(ranked_market)
            proposals = self._generate_multi_strategy_proposals(market, evidences)

            if not proposals:
                previews.append(
                    ProposalPreview(
                        market=market,
                        rank_score=ranked_market.score,
                        ranking_reasons=ranked_market.reasons,
                        evidences=evidences,
                        suggested_side='hold',
                        confidence=0.0,
                        model_probability=market.yes_price,
                        market_implied_probability=market.yes_price,
                        edge_bps=0,
                        suggested_stake_usd=0.0,
                        explanation='No edge passed the current thresholds.',
                        risk_flags=[],
                        should_trade=False,
                    )
                )
                continue

            # Select the best proposal (highest edge_bps)
            best_proposal = max(proposals, key=lambda p: p.edge_bps)
            ok, flags = self.risk.evaluate(session, market, best_proposal)
            previews.append(
                ProposalPreview(
                    market=market,
                    rank_score=ranked_market.score,
                    ranking_reasons=ranked_market.reasons,
                    evidences=evidences,
                    suggested_side=best_proposal.side,
                    confidence=best_proposal.confidence,
                    model_probability=best_proposal.model_probability,
                    market_implied_probability=best_proposal.market_implied_probability,
                    edge_bps=best_proposal.edge_bps,
                    suggested_stake_usd=best_proposal.stake_usd,
                    explanation=best_proposal.explanation,
                    risk_flags=flags,
                    should_trade=ok,
                )
            )
        return previews
