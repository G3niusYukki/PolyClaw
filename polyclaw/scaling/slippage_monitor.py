"""Slippage Monitor — tracks and alerts on execution slippage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# In-memory slippage records (keyed by market_id)
_slippage_records: dict[str, list['SlippageRecord']] = {}

# Slippage thresholds
DEFAULT_AVG_SLIPPAGE_THRESHOLD = 0.005  # 0.5% average slippage triggers alert


@dataclass
class SlippageRecord:
    """Record of a single fill with slippage tracking."""
    market_id: str
    expected_price: float
    actual_price: float
    slippage_pct: float  # (actual - expected) / expected, positive = worse
    size_usd: float
    timestamp: datetime = field(default_factory=utcnow)


class SlippageMonitor:
    """
    Monitors execution slippage and tracks statistics.

    Stores slippage records in memory (per process) and provides
    statistics by market, size bucket, and overall.

    Alerts when average slippage exceeds the configured threshold.
    """

    def __init__(
        self,
        avg_threshold_pct: float = DEFAULT_AVG_SLIPPAGE_THRESHOLD,
    ):
        self.avg_threshold_pct = avg_threshold_pct
        self._records: dict[str, list[SlippageRecord]] = {}

    def track_fill(
        self,
        expected_price: float,
        actual_price: float,
        market_id: str,
        size_usd: float,
        session: 'Session | None' = None,
    ) -> SlippageRecord:
        """
        Track a fill and calculate slippage.

        Args:
            expected_price: Expected fill price at submission
            actual_price: Actual execution price
            market_id: Market identifier
            size_usd: Order size in USD
            session: Optional SQLAlchemy session (for future DB persistence)

        Returns:
            The SlippageRecord created for this fill
        """
        if expected_price <= 0:
            slippage_pct = 0.0
        else:
            slippage_pct = round((actual_price - expected_price) / expected_price, 6)

        record = SlippageRecord(
            market_id=market_id,
            expected_price=expected_price,
            actual_price=actual_price,
            slippage_pct=slippage_pct,
            size_usd=size_usd,
            timestamp=utcnow(),
        )

        # Store in memory
        if market_id not in self._records:
            self._records[market_id] = []
        self._records[market_id].append(record)

        return record

    def get_slippage_stats(
        self,
        session: 'Session | None' = None,
        window_days: int = 7,
    ) -> dict:
        """
        Get slippage statistics over a window.

        Args:
            session: Optional SQLAlchemy session
            window_days: Number of days to look back (default 7)

        Returns:
            dict with:
              - avg_slippage_pct: overall average slippage
              - max_slippage_pct: worst single slippage
              - by_market: {market_id: avg_slippage_pct}
              - by_size_bucket: {bucket: avg_slippage_pct}
              - total_fills: int
        """
        from datetime import timedelta
        cutoff = utcnow() - timedelta(days=window_days)

        all_records: list[SlippageRecord] = []
        for records in self._records.values():
            all_records.extend(r for r in records if r.timestamp >= cutoff)

        if not all_records:
            return {
                'avg_slippage_pct': 0.0,
                'max_slippage_pct': 0.0,
                'by_market': {},
                'by_size_bucket': {},
                'total_fills': 0,
            }

        # Overall stats
        slippage_values = [abs(r.slippage_pct) for r in all_records]
        avg_slippage = sum(slippage_values) / len(slippage_values)
        max_slippage = max(slippage_values)

        # By market
        by_market: dict[str, list[float]] = {}
        for r in all_records:
            by_market.setdefault(r.market_id, []).append(abs(r.slippage_pct))
        by_market_avg = {
            mid: sum(vals) / len(vals)
            for mid, vals in by_market.items()
        }

        # By size bucket
        by_bucket: dict[str, list[float]] = {}
        for r in all_records:
            bucket = self._size_bucket(r.size_usd)
            by_bucket.setdefault(bucket, []).append(abs(r.slippage_pct))
        by_bucket_avg = {
            bkt: round(sum(vals) / len(vals), 6)
            for bkt, vals in by_bucket.items()
        }

        return {
            'avg_slippage_pct': round(avg_slippage, 6),
            'max_slippage_pct': round(max_slippage, 6),
            'by_market': {k: round(v, 6) for k, v in by_market_avg.items()},
            'by_size_bucket': by_bucket_avg,
            'total_fills': len(all_records),
        }

    def is_slippage_excessive(self, session: 'Session | None' = None) -> bool:
        """
        Check if average slippage exceeds the configured threshold.

        Args:
            session: Optional SQLAlchemy session

        Returns:
            True if avg slippage > self.avg_threshold_pct
        """
        stats = self.get_slippage_stats(session=session, window_days=7)
        avg = stats['avg_slippage_pct']
        return avg > self.avg_threshold_pct

    def get_excessive_slippage_markets(
        self,
        session: 'Session | None' = None,
    ) -> list[tuple[str, float]]:
        """
        Get markets with average slippage > threshold.

        Args:
            session: Optional SQLAlchemy session

        Returns:
            List of (market_id, avg_slippage_pct) tuples for markets exceeding threshold
        """
        stats = self.get_slippage_stats(session=session)
        return [
            (mid, slip)
            for mid, slip in stats['by_market'].items()
            if slip > self.avg_threshold_pct
        ]

    def _size_bucket(self, size_usd: float) -> str:
        """Categorize order size into buckets."""
        if size_usd <= 10:
            return 'micro (<=$10)'
        elif size_usd <= 50:
            return 'small ($10-$50)'
        elif size_usd <= 200:
            return 'medium ($50-$200)'
        elif size_usd <= 1000:
            return 'large ($200-$1K)'
        else:
            return 'xlarge (>$1K)'
