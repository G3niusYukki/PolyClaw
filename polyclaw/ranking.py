from dataclasses import dataclass
from datetime import timedelta

from polyclaw.domain import MarketSnapshot
from polyclaw.timeutils import utcnow


@dataclass
class RankedMarket:
    market: MarketSnapshot
    score: float
    reasons: list[str]


class MarketRanker:
    def rank(self, markets: list[MarketSnapshot], limit: int | None = None) -> list[RankedMarket]:
        ranked = [self._score_market(m) for m in markets]
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked[:limit] if limit else ranked

    def _score_market(self, market: MarketSnapshot) -> RankedMarket:
        score = 0.0
        reasons: list[str] = []

        if market.liquidity_usd >= 10000:
            score += 30
            reasons.append('strong_liquidity')
        elif market.liquidity_usd >= 3000:
            score += 18
            reasons.append('acceptable_liquidity')
        else:
            score -= 20
            reasons.append('weak_liquidity')

        if market.volume_24h_usd >= 5000:
            score += 20
            reasons.append('strong_recent_volume')
        elif market.volume_24h_usd >= 1000:
            score += 10
            reasons.append('acceptable_recent_volume')
        else:
            score -= 8
            reasons.append('thin_recent_volume')

        if 0 < market.spread_bps <= 150:
            score += 20
            reasons.append('tight_spread')
        elif market.spread_bps <= 400:
            score += 10
            reasons.append('reasonable_spread')
        else:
            score -= 15
            reasons.append('wide_spread')

        if market.closes_at:
            remaining = market.closes_at - utcnow()
            if timedelta(hours=12) <= remaining <= timedelta(days=45):
                score += 15
                reasons.append('good_time_horizon')
            elif remaining < timedelta(hours=12):
                score -= 10
                reasons.append('too_close_to_resolution')
            elif remaining > timedelta(days=120):
                score -= 5
                reasons.append('very_long_dated')

        title = market.title.lower()
        if any(token in title for token in ['gta vi', 'jesus christ', 'album before gta']):
            score -= 12
            reasons.append('novelty_market')
        if any(token in title for token in ['will ', ' before ', ' convicted', ' ceasefire']):
            score += 6
            reasons.append('clear_binary_wording')

        return RankedMarket(market=market, score=round(score, 2), reasons=reasons)
