from polyclaw.domain import EvidenceItem, MarketSnapshot


class SampleEvidenceProvider:
    def gather(self, market: MarketSnapshot) -> list[EvidenceItem]:
        if 'election' in market.title.lower():
            return [
                EvidenceItem(source='polling', summary='Recent polling trend modestly improved for candidate A.', direction='yes', confidence=0.66),
                EvidenceItem(source='fundraising', summary='Fundraising remains competitive but not dominant.', direction='yes', confidence=0.58),
                EvidenceItem(source='opposition', summary='Opponent still retains incumbency advantage.', direction='no', confidence=0.54),
            ]
        return [
            EvidenceItem(source='macro-data', summary='Inflation cooled slightly, supportive of a cut.', direction='yes', confidence=0.64),
            EvidenceItem(source='fed-speak', summary='Several officials remain cautious on timing.', direction='no', confidence=0.62),
            EvidenceItem(source='rates-market', summary='External rates pricing implies elevated uncertainty.', direction='neutral', confidence=0.5),
        ]
