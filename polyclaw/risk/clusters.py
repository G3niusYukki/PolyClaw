import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from polyclaw.models import AuditLog


@dataclass
class ClusterExposure:
    """Exposure summary for an event cluster."""
    cluster_key: str
    exposure_usd: float
    position_count: int
    max_allowed_pct: float


# Regex patterns for extracting cluster keys from market titles/categories
# Match groups: (year, keyword) - year always comes first in the key
_CLUSTER_PATTERNS = [
    # "2024 US Presidential Election" -> "2024-us-presidential-election"
    # Capture: year + category-specific keywords
    re.compile(r'\b(20\d{2}|19\d{2})\b[-_\s]?(us[-_\s]?presidential[-_\s]?election)\b', re.IGNORECASE),
    # "2024 Bitcoin" or "2024 BTC" (year immediately followed by keyword)
    re.compile(r'\b(20\d{2}|19\d{2})\b[-_\s]+(bitcoin|btc|ethereum|eth)\b', re.IGNORECASE),
    # "Bitcoin 2024" or "BTC 2024" (keyword immediately followed by year)
    re.compile(r'\b(bitcoin|btc|ethereum|eth)\b[-_\s]+(20\d{2}|19\d{2})\b', re.IGNORECASE),
    # Generic year extraction: "Some event in 2024" -> "2024"
    re.compile(r'\b(20\d{2}|19\d{2})\b'),
]


def extract_cluster_from_title(title: str, category: str = '') -> str:
    """
    Attempt to extract a cluster key from a market title or category.

    Examples:
      "Who wins 2024 US Presidential Election" -> "2024-us-presidential-election"
      "2024 Bitcoin" -> "2024-bitcoin"
      "BTC 2024" -> "btc-2024"
      "Random market about tech" -> "general"
    """
    combined = f"{title} {category}".strip()
    if not combined:
        return 'general'

    # Try each pattern
    for pattern in _CLUSTER_PATTERNS:
        match = pattern.search(combined)
        if match:
            groups = match.groups()
            if len(groups) >= 2 and groups[0] and groups[1]:
                # Normal two-group pattern: (year, keyword) or (keyword, year)
                year = groups[0] if groups[0] and any(c.isdigit() for c in groups[0]) else groups[1]
                keyword = groups[1] if year == groups[0] else groups[0]
                key = f"{year.lower()}-{re.sub(r'[^a-z0-9]+', '-', keyword.lower()).strip('-')}"
                return key
            elif len(groups) == 2 and groups[0]:
                # Single-group pattern (generic year)
                key = groups[0].lower()
                return key
            else:
                # Fallback to full match
                key = match.group(0).lower()
                key = re.sub(r'[^a-z0-9]+', '-', key).strip('-')
                return key

    return 'general'


class EventClusterTracker:
    """
    Tracks market-to-cluster associations and calculates cluster-level exposure.
    """

    def __init__(self, db_session: Session):
        self.session = db_session

    def map_market_to_cluster(
        self, market_id: str, cluster_key: str, confidence: float = 1.0
    ) -> AuditLog:
        """
        Associate a market with an event cluster.

        Stores the mapping in the AuditLog table with action='market_cluster_mapping'.
        """
        log = AuditLog(
            action='market_cluster_mapping',
            payload=f"{market_id}|{cluster_key}|{confidence:.2f}",
            result='ok',
        )
        self.session.add(log)
        self.session.flush()
        return log

    def get_cluster_exposure(self, cluster_key: str, positions: list) -> float:
        """
        Calculate total exposure for a given cluster.

        Sums the notional_usd of all open positions that belong to markets
        in the specified cluster.
        """
        if not positions:
            return 0.0

        # Get market IDs associated with this cluster from audit logs
        stmt = select(AuditLog.payload).where(
            AuditLog.action == 'market_cluster_mapping'
        )
        rows = self.session.execute(stmt).scalars().all()

        cluster_market_ids: set[str] = set()
        for row in rows:
            parts = row.split('|')
            if len(parts) >= 2 and parts[1] == cluster_key:
                cluster_market_ids.add(parts[0])

        total = 0.0
        for pos in positions:
            if not pos.is_open:
                continue
            # Check by market_id first
            if pos.market_id in cluster_market_ids or (
                getattr(pos, 'event_key', '') != '' and cluster_key == extract_cluster_from_title(
                    getattr(pos, 'event_key', '')
                )
            ):
                total += abs(pos.notional_usd)

        return total

    def get_all_clusters(self) -> list[str]:
        """List all known cluster keys."""
        stmt = select(AuditLog.payload).where(
            AuditLog.action == 'market_cluster_mapping'
        )
        rows = self.session.execute(stmt).scalars().all()

        clusters: set[str] = set()
        for row in rows:
            parts = row.split('|')
            if len(parts) >= 2:
                clusters.add(parts[1])

        return sorted(clusters)

    def get_cluster_exposure_summary(
        self, cluster_key: str, positions: list, max_allowed_pct: float = 30.0
    ) -> ClusterExposure:
        """Get a full ClusterExposure summary for a cluster."""
        exposure = self.get_cluster_exposure(cluster_key, positions)
        open_positions = [p for p in positions if p.is_open]

        # Count positions in this cluster
        stmt = select(AuditLog.payload).where(
            AuditLog.action == 'market_cluster_mapping'
        )
        rows = self.session.execute(stmt).scalars().all()
        cluster_market_ids: set[str] = set()
        for row in rows:
            parts = row.split('|')
            if len(parts) >= 2 and parts[1] == cluster_key:
                cluster_market_ids.add(parts[0])

        count = sum(
            1 for p in open_positions
            if p.market_id in cluster_market_ids or cluster_key == extract_cluster_from_title(getattr(p, 'event_key', ''))
        )

        return ClusterExposure(
            cluster_key=cluster_key,
            exposure_usd=exposure,
            position_count=count,
            max_allowed_pct=max_allowed_pct,
        )
