"""Smart Money strategy — follows whale wallets and on-chain signals.

Combines on-chain signals (whale positions, tracked wallet activity, unusual volume)
with LLM probability estimates. Only fires when Smart Money direction aligns with
LLM baseline, with confidence boosted by multi-signal alignment.
"""

import logging

from polyclaw.config import settings
from polyclaw.data.onchain import OnChainAnalyzer, UnusualActivity, WalletActivity, WhalePosition
from polyclaw.domain import MarketSnapshot
from polyclaw.llm.client import LLMClient
from polyclaw.llm.parser import LLMProbabilityEstimate, parse_probability_response
from polyclaw.llm.prompts import build_probability_prompt
from polyclaw.strategies.base import BaseStrategy, Side, Signal

logger = logging.getLogger(__name__)


class SmartMoneyStrategy(BaseStrategy):
    """Strategy that follows Smart Money signals aligned with LLM estimates."""

    strategy_id: str = 'smart_money'
    name: str = 'Smart Money'
    version: str = '1.0.0'

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        onchain: OnChainAnalyzer | None = None,
    ) -> None:
        self._llm = llm_client
        self._onchain = onchain

    @property
    def enabled(self) -> bool:
        return bool(settings.llm_api_key) and settings.onchain_tracking_enabled

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_onchain(self) -> OnChainAnalyzer:
        if self._onchain is None:
            self._onchain = OnChainAnalyzer()
        return self._onchain

    def compute_features(self, market: MarketSnapshot) -> dict:
        """Compute on-chain features: whale positions, tracked wallets, unusual activity."""
        # Step 1: Get LLM baseline
        llm = self._get_llm()
        system_prompt, user_prompt = build_probability_prompt(market)
        raw = llm.complete(system_prompt, user_prompt)
        estimate = parse_probability_response(raw, market.market_id, settings.llm_model) if raw else None

        if estimate is None:
            return {'llm_estimate': None, 'onchain_signals': []}

        # Step 2: Gather on-chain data
        onchain = self._get_onchain()
        market_addresses = [market.market_id]
        signals: list[dict] = []

        # Whale positions
        try:
            whales = onchain.get_large_positions(market_addresses)
            for w in whales:
                signals.append({
                    'type': 'whale_position',
                    'direction': w.side,
                    'magnitude': min(1.0, w.size_usd / 10000.0),
                    'size_usd': w.size_usd,
                    'wallet': w.wallet_address[:10] + '...',
                })
        except Exception as exc:
            logger.debug('Whale position query failed: %s', exc)

        # Tracked wallets
        tracked = getattr(settings, 'onchain_tracked_wallets', '')
        if tracked:
            wallets = [w.strip() for w in tracked.split(',') if w.strip()]
            try:
                activities = onchain.track_known_wallets(wallets, market_addresses)
                for a in activities:
                    signals.append({
                        'type': 'tracked_wallet',
                        'direction': a.side,
                        'magnitude': 0.5,
                        'size_usd': a.size_usd,
                        'wallet': a.wallet_address[:10] + '...',
                        'label': a.label,
                    })
            except Exception as exc:
                logger.debug('Tracked wallet query failed: %s', exc)

        # Unusual activity
        try:
            unusual = onchain.detect_unusual_activity(market_addresses)
            for u in unusual:
                signals.append({
                    'type': 'unusual_activity',
                    'direction': u.direction,
                    'magnitude': u.magnitude,
                    'activity_type': u.activity_type,
                    'details': u.details,
                })
        except Exception as exc:
            logger.debug('Unusual activity detection failed: %s', exc)

        return {
            'llm_estimate': estimate,
            'onchain_signals': signals,
        }

    def generate_signals(self, market: MarketSnapshot, features: dict) -> Signal | None:
        """Generate signal when Smart Money aligns with LLM estimate."""
        estimate: LLMProbabilityEstimate | None = features.get('llm_estimate')
        onchain_signals: list[dict] = features.get('onchain_signals', [])

        if estimate is None or not onchain_signals:
            return None

        if estimate.confidence < settings.min_confidence:
            return None

        # Aggregate on-chain signals
        yes_weight = 0.0
        no_weight = 0.0
        signal_count = 0

        for sig in onchain_signals:
            direction = sig.get('direction', '')
            magnitude = float(sig.get('magnitude', 0.0))
            if direction == 'yes':
                yes_weight += magnitude
                signal_count += 1
            elif direction == 'no':
                no_weight += magnitude
                signal_count += 1
            # 'unknown' directions don't contribute

        if signal_count == 0:
            return None

        # Determine on-chain consensus
        total_weight = yes_weight + no_weight
        if total_weight == 0:
            return None

        onchain_direction = 'yes' if yes_weight > no_weight else 'no'
        onchain_magnitude = max(yes_weight, no_weight) / total_weight

        # Check alignment with LLM estimate
        llm_direction = 'yes' if estimate.estimated_probability_yes > market.yes_price else 'no'

        if onchain_direction != llm_direction:
            logger.info(
                'SmartMoney: direction mismatch for %s (llm=%s, onchain=%s)',
                market.market_id, llm_direction, onchain_direction,
            )
            return None

        # Direction is aligned — boost confidence based on signal count and magnitude
        confidence_boost = min(0.15, signal_count * 0.03 + onchain_magnitude * 0.05)
        confidence = min(0.95, estimate.confidence + confidence_boost)

        # Calculate edge using LLM probability
        edge_bps_yes = int((estimate.estimated_probability_yes - market.yes_price) * 10000)

        if llm_direction == 'yes' and edge_bps_yes > settings.min_edge_bps:
            side = Side.YES
            edge_bps = edge_bps_yes
        elif llm_direction == 'no' and edge_bps_yes < -settings.min_edge_bps:
            side = Side.NO
            edge_bps = -edge_bps_yes
        else:
            return None

        # Spread/liquidity filters
        if market.spread_bps > settings.max_spread_bps:
            return None
        if market.liquidity_usd < settings.min_liquidity_usd:
            return None

        return Signal(
            strategy_id=self.strategy_id,
            side=side,
            confidence=round(confidence, 4),
            edge_bps=edge_bps,
            explanation=(
                f'SmartMoney: {signal_count} on-chain signals aligned with LLM '
                f'(direction={onchain_direction}, magnitude={onchain_magnitude:.2f}), '
                f'llm_yes={estimate.estimated_probability_yes:.3f}, market_yes={market.yes_price:.3f}'
            ),
            model_probability=estimate.estimated_probability_yes,
            market_implied_probability=market.yes_price,
            features_used={
                'onchain_signal_count': signal_count,
                'onchain_direction': onchain_direction,
                'onchain_magnitude': round(onchain_magnitude, 3),
                'yes_weight': round(yes_weight, 3),
                'no_weight': round(no_weight, 3),
            },
        )
