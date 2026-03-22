from polyclaw.domain import EvidenceItem
from polyclaw.ranking import RankedMarket


class HeuristicEvidenceEngine:
    def build(self, ranked_market: RankedMarket) -> list[EvidenceItem]:
        market = ranked_market.market
        items: list[EvidenceItem] = []

        if market.liquidity_usd >= 10000:
            items.append(EvidenceItem(source='market_microstructure', summary='Liquidity is strong enough for safer execution and price discovery.', direction='yes', confidence=0.58))
        elif market.liquidity_usd < 3000:
            items.append(EvidenceItem(source='market_microstructure', summary='Liquidity is weak, which reduces confidence in quoted probabilities.', direction='no', confidence=0.62))

        if 0 < market.spread_bps <= 150:
            items.append(EvidenceItem(source='spread_check', summary='Bid/ask spread is tight, improving execution quality.', direction='yes', confidence=0.56))
        elif market.spread_bps > 400:
            items.append(EvidenceItem(source='spread_check', summary='Wide spread suggests poor execution quality and uncertain price discovery.', direction='no', confidence=0.64))

        title = market.title.lower()
        if any(token in title for token in ['ceasefire', 'convicted', 'fed', 'election']):
            items.append(EvidenceItem(source='market_type', summary='This looks like a concrete information-driven event rather than a pure meme market.', direction='yes', confidence=0.57))
        if any(token in title for token in ['gta vi', 'jesus christ']):
            items.append(EvidenceItem(source='market_type', summary='This appears novelty-heavy and may be less suitable for disciplined event trading.', direction='no', confidence=0.66))

        if market.volume_24h_usd >= 5000:
            items.append(EvidenceItem(source='recent_activity', summary='Recent volume indicates active participation and fresher pricing.', direction='yes', confidence=0.55))
        elif market.volume_24h_usd < 1000:
            items.append(EvidenceItem(source='recent_activity', summary='Recent volume is thin, so prices may be stale or noisy.', direction='no', confidence=0.6))

        if not items:
            items.append(EvidenceItem(source='baseline', summary='No strong heuristics detected; keep neutral posture.', direction='neutral', confidence=0.5))
        return items
