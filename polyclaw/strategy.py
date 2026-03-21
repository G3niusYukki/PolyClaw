from polyclaw.config import settings
from polyclaw.domain import DecisionProposal, EvidenceItem, MarketSnapshot


class StrategyEngine:
    def score_market(self, market: MarketSnapshot, evidences: list[EvidenceItem]) -> DecisionProposal | None:
        yes_strength = sum(e.confidence for e in evidences if e.direction == 'yes')
        no_strength = sum(e.confidence for e in evidences if e.direction == 'no')
        neutral = sum(e.confidence for e in evidences if e.direction == 'neutral')

        total = yes_strength + no_strength + neutral
        if total <= 0:
            return None

        raw_probability = 0.5 + ((yes_strength - no_strength) / max(total, 1e-6)) * 0.25
        model_probability = min(max(raw_probability, 0.03), 0.97)

        if model_probability >= market.yes_price:
            side = 'yes'
            implied = market.yes_price
            edge = int((model_probability - implied) * 10000)
        else:
            side = 'no'
            implied = market.no_price
            edge = int(((1 - model_probability) - implied) * 10000)

        confidence = min(0.95, 0.45 + abs(yes_strength - no_strength) / max(total, 1e-6) * 0.5)
        if confidence < settings.min_confidence or edge < settings.min_edge_bps:
            return None

        stake = min(settings.max_position_usd, 10 + edge / 100)
        explanation = (
            f'Model probability={model_probability:.3f}; market yes={market.yes_price:.3f}; '
            f'yes_strength={yes_strength:.2f}; no_strength={no_strength:.2f}; neutral={neutral:.2f}.'
        )
        return DecisionProposal(
            side=side,
            confidence=confidence,
            model_probability=model_probability,
            market_implied_probability=implied,
            edge_bps=edge,
            stake_usd=round(stake, 2),
            explanation=explanation,
            risk_flags=[],
        )
