from datetime import timedelta

from polyclaw.domain import MarketSnapshot
from polyclaw.ranking import MarketRanker
from polyclaw.timeutils import utcnow


def test_ranker_prefers_liquid_tight_clear_market():
    now = utcnow()
    good = MarketSnapshot('1', 'Will candidate X be convicted?', '', 0.45, 0.55, 50, 20000, 9000, 'news', 'a', now + timedelta(days=10), now)
    weak = MarketSnapshot('2', 'Will Jesus Christ return before GTA VI?', '', 0.48, 0.52, 600, 1000, 200, 'novelty', 'b', now + timedelta(days=120), now)
    ranked = MarketRanker().rank([weak, good])
    assert ranked[0].market.market_id == '1'
    assert ranked[0].score > ranked[1].score
