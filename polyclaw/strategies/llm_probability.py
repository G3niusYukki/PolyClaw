"""LLM Probability Estimation strategy.

Uses a large language model to estimate event probabilities and compares
them against market-implied probabilities to find edge.
"""

import logging

from polyclaw.config import settings
from polyclaw.domain import MarketSnapshot
from polyclaw.llm.client import LLMClient
from polyclaw.llm.parser import LLMProbabilityEstimate, parse_probability_response
from polyclaw.llm.prompts import build_probability_prompt
from polyclaw.strategies.base import BaseStrategy, Side, Signal

logger = logging.getLogger(__name__)


class LLMProbabilityStrategy(BaseStrategy):
    """Strategy that uses LLM probability estimates vs market prices."""

    strategy_id: str = 'llm_probability'
    name: str = 'LLM Probability Estimation'
    version: str = '1.0.0'

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client

    @property
    def enabled(self) -> bool:
        return bool(settings.llm_api_key)

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Query LLM for probability estimate."""
        llm = self._get_llm()
        system_prompt, user_prompt = build_probability_prompt(market)

        raw = llm.complete(system_prompt, user_prompt)
        if raw is None:
            logger.info('LLM returned no response for market %s', market.market_id)
            return {'llm_estimate': None}

        estimate = parse_probability_response(raw, market.market_id, settings.llm_model)
        if estimate is None:
            logger.info('Failed to parse LLM estimate for market %s', market.market_id)
            return {'llm_estimate': None}

        logger.info(
            'LLM estimate for %s: prob_yes=%.3f confidence=%.3f',
            market.market_id, estimate.estimated_probability_yes, estimate.confidence,
        )
        return {'llm_estimate': estimate}

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal when LLM estimate diverges from market price."""
        estimate: LLMProbabilityEstimate | None = features.get('llm_estimate')
        if estimate is None:
            return None

        # Minimum confidence from LLM
        if estimate.confidence < settings.min_confidence:
            return None

        # Calculate edge: difference between LLM estimate and market implied
        market_prob_yes = market.yes_price
        llm_prob_yes = estimate.estimated_probability_yes
        edge_bps_yes = int((llm_prob_yes - market_prob_yes) * 10000)

        # Determine direction and edge
        if edge_bps_yes > settings.min_edge_bps:
            side = Side.YES
            edge_bps = edge_bps_yes
        elif edge_bps_yes < -settings.min_edge_bps:
            side = Side.NO
            edge_bps = -edge_bps_yes
        else:
            return None

        # Filter by spread and liquidity
        if market.spread_bps > settings.max_spread_bps:
            return None
        if market.liquidity_usd < settings.min_liquidity_usd:
            return None

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(estimate.confidence, 4),
            edge_bps=edge_bps,
            explanation=(
                f'LLM Probability: model_yes={llm_prob_yes:.3f}, market_yes={market_prob_yes:.3f}, '
                f'edge={edge_bps}bps, confidence={estimate.confidence:.3f}. '
                f'Reasoning: {estimate.reasoning[:200]}'
            ),
            model_probability=llm_prob_yes,
            market_implied_probability=market_prob_yes,
            features_used={
                'llm_probability_yes': round(llm_prob_yes, 4),
                'llm_confidence': round(estimate.confidence, 4),
                'key_factors': estimate.key_factors,
            },
        )
