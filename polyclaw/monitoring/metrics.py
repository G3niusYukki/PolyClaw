"""Metrics Collection — logging-based metrics emission."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Pre-defined metric names
METRIC_SIGNAL_GENERATION_LATENCY = 'signal_generation_latency'
METRIC_ORDER_SUBMISSION_LATENCY = 'order_submission_latency'
METRIC_DATA_FRESHNESS_SECONDS = 'data_freshness_seconds'
METRIC_UNREALIZED_PNL = 'unrealized_pnl'
METRIC_STRATEGY_SHARPE_7D = 'strategy_sharpe_7d'
METRIC_RECONCILIATION_ERROR_PCT = 'reconciliation_error_pct'
METRIC_ORDER_FILL_RATE = 'order_fill_rate'


class MetricsCollector:
    """Collects and logs metrics for PolyClaw."""

    def emit_metric(
        self,
        name: str,
        value: float,
        unit: str = 'None',
        dimensions: dict[str, str] | None = None,
    ) -> None:
        logger.debug(
            '[MetricsCollector] metric: name=%s value=%s unit=%s dimensions=%s',
            name, value, unit, dimensions or '',
        )
