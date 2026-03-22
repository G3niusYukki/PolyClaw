"""
Health checks for PolyClaw — validates connectivity and data freshness.

Provides a comprehensive HealthChecker that tests database connectivity,
Polymarket API reachability, CTF contract accessibility, data freshness,
and kill switch status. Results are returned as a structured HealthStatus.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from polyclaw.models import Market
from polyclaw.providers.ctf import PolymarketCTFProvider
from polyclaw.providers.polymarket_gamma import PolymarketGammaProvider
from polyclaw.safety import kill_switch_state
from polyclaw.timeutils import utcnow

logger = logging.getLogger(__name__)


class ComponentStatus(str, Enum):
    """Status values for individual health check components."""
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNHEALTHY = 'unhealthy'


@dataclass
class ComponentHealth:
    """Result of a single health check for one component."""
    component_name: str
    status: ComponentStatus
    latency_ms: float
    error_message: str | None = None


@dataclass
class HealthStatus:
    """Overall health status of the PolyClaw system."""
    overall_status: ComponentStatus  # healthy, degraded, or unhealthy
    checks: list[ComponentHealth] = field(default_factory=list)
    timestamp: datetime = field(default_factory=utcnow)


class HealthChecker:
    """
    Runs health checks against PolyClaw's dependencies and system state.

    Checks performed:
      - Database connectivity and latency
      - Polymarket API reachability and latency
      - CTF contract accessibility
      - Data freshness (latest market data < 10 minutes old)
      - Kill switch status

    Overall status rules:
      - healthy:  ALL checks pass (status=healthy)
      - degraded: ANY check is degraded (status=degraded)
      - unhealthy: ANY check is unhealthy OR any check fails
    """

    DATA_FRESHNESS_MINUTES: int = 10

    def __init__(
        self,
        session: Session,
        ctf_provider: PolymarketCTFProvider | None = None,
        polymarket_api: PolymarketGammaProvider | None = None,
    ):
        """
        Initialize the health checker.

        Args:
            session: SQLAlchemy database session.
            ctf_provider: CTF provider instance (default: creates one).
            polymarket_api: Polymarket API provider instance (default: creates one).
        """
        self.session = session
        self.ctf_provider = ctf_provider or PolymarketCTFProvider()
        self.polymarket_api = polymarket_api or PolymarketGammaProvider()

    def check(self) -> HealthStatus:
        """
        Run all health checks and return a consolidated HealthStatus.

        Returns:
            A HealthStatus with overall_status and individual ComponentHealth results.
        """
        checks: list[ComponentHealth] = []

        checks.append(self.check_database())
        checks.append(self.check_polymarket_api())
        checks.append(self.check_ctf_contract())
        checks.append(self.check_data_freshness())
        checks.append(self.check_kill_switch())

        # Determine overall status
        if any(c.status == ComponentStatus.UNHEALTHY for c in checks):
            overall = ComponentStatus.UNHEALTHY
        elif any(c.status == ComponentStatus.DEGRADED for c in checks):
            overall = ComponentStatus.DEGRADED
        else:
            overall = ComponentStatus.HEALTHY

        return HealthStatus(
            overall_status=overall,
            checks=checks,
            timestamp=utcnow(),
        )

    def check_database(self) -> ComponentHealth:
        """
        Test database connectivity and measure query latency.

        Runs a simple SELECT 1 query to verify the database is reachable.

        Returns:
            A ComponentHealth with status, latency_ms, and error_message if any.
        """
        name = 'database'
        start = time.perf_counter()
        try:
            self.session.execute(text('SELECT 1'))
            self.session.commit()
            latency_ms = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.HEALTHY,
                latency_ms=latency_ms,
                error_message=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error("Database health check failed: %s", exc)
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    def check_polymarket_api(self) -> ComponentHealth:
        """
        Test Polymarket API reachability and measure latency.

        Makes a lightweight API call to verify the Gamma endpoint is reachable.

        Returns:
            A ComponentHealth with status, latency_ms, and error_message if any.
        """
        name = 'polymarket_api'
        start = time.perf_counter()
        try:
            # Use list_markets with a small limit to minimize data transfer
            self.polymarket_api.list_markets(limit=1)
            latency_ms = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.HEALTHY,
                latency_ms=latency_ms,
                error_message=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("Polymarket API health check failed: %s", exc)
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    def check_ctf_contract(self) -> ComponentHealth:
        """
        Test CTF contract reachability via Polygon RPC.

        Makes an eth_blockNumber RPC call to verify the Polygon RPC endpoint
        is accessible and responsive.

        Returns:
            A ComponentHealth with status, latency_ms, and error_message if any.
        """
        name = 'ctf_contract'
        start = time.perf_counter()
        try:
            result = self.ctf_provider._rpc_call('eth_blockNumber', [])
            latency_ms = (time.perf_counter() - start) * 1000
            if result is not None:
                return ComponentHealth(
                    component_name=name,
                    status=ComponentStatus.HEALTHY,
                    latency_ms=latency_ms,
                    error_message=None,
                )
            else:
                return ComponentHealth(
                    component_name=name,
                    status=ComponentStatus.UNHEALTHY,
                    latency_ms=latency_ms,
                    error_message='eth_blockNumber returned null',
                )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("CTF contract health check failed: %s", exc)
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    def check_data_freshness(self) -> ComponentHealth:
        """
        Verify that the latest market data is less than 10 minutes old.

        Queries the most recent Market.fetched_at timestamp and compares
        it against the configured freshness threshold.

        Returns:
            A ComponentHealth with status, latency_ms, and error_message if any.
        """
        name = 'data_freshness'
        start = time.perf_counter()
        try:
            latest = self.session.scalar(
                select(Market.fetched_at)
                .order_by(Market.fetched_at.desc())
                .limit(1)
            )
            latency_ms = (time.perf_counter() - start) * 1000

            if latest is None:
                return ComponentHealth(
                    component_name=name,
                    status=ComponentStatus.DEGRADED,
                    latency_ms=latency_ms,
                    error_message='No market data in database',
                )

            age_minutes = (utcnow() - latest).total_seconds() / 60.0
            if age_minutes > self.DATA_FRESHNESS_MINUTES:
                return ComponentHealth(
                    component_name=name,
                    status=ComponentStatus.UNHEALTHY,
                    latency_ms=latency_ms,
                    error_message=f'Latest data is {age_minutes:.1f} minutes old (threshold: {self.DATA_FRESHNESS_MINUTES} min)',
                )
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.HEALTHY,
                latency_ms=latency_ms,
                error_message=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("Data freshness health check failed: %s", exc)
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    def check_kill_switch(self) -> ComponentHealth:
        """
        Check whether the kill switch is currently active.

        Returns:
            A ComponentHealth. CRITICAL/unhealthy if kill switch is active,
            healthy otherwise.
        """
        name = 'kill_switch'
        start = time.perf_counter()
        try:
            state = kill_switch_state(self.session)
            latency_ms = (time.perf_counter() - start) * 1000

            if state.get('enabled', False):
                return ComponentHealth(
                    component_name=name,
                    status=ComponentStatus.UNHEALTHY,
                    latency_ms=latency_ms,
                    error_message='Kill switch is ACTIVE — trading is halted',
                )
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.HEALTHY,
                latency_ms=latency_ms,
                error_message=None,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("Kill switch health check failed: %s", exc)
            return ComponentHealth(
                component_name=name,
                status=ComponentStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error_message=str(exc),
            )
