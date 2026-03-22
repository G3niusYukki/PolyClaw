"""Metrics Collection — CloudWatch metrics emission for PolyClaw operations."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Pre-defined metric names (matching CloudWatch alarm definitions)
METRIC_SIGNAL_GENERATION_LATENCY = 'signal_generation_latency'
METRIC_ORDER_SUBMISSION_LATENCY = 'order_submission_latency'
METRIC_DATA_FRESHNESS_SECONDS = 'data_freshness_seconds'
METRIC_UNREALIZED_PNL = 'unrealized_pnl'
METRIC_STRATEGY_SHARPE_7D = 'strategy_sharpe_7d'
METRIC_RECONCILIATION_ERROR_PCT = 'reconciliation_error_pct'
METRIC_ORDER_FILL_RATE = 'order_fill_rate'


class MetricsCollector:
    """
    Emits CloudWatch metrics for PolyClaw operations.

    Uses boto3 CloudWatch client when AWS credentials are available.
    Falls back to logging when not configured (e.g., local development).
    """

    def __init__(
        self,
        namespace: str = 'PolyClaw',
        region_name: str | None = None,
    ):
        self.namespace = namespace
        self._client = None
        self._region_name = region_name

    @property
    def client(self):
        """Lazy-initialize boto3 CloudWatch client."""
        if self._client is None:
            try:
                import boto3
                kwargs: dict[str, Any] = {}
                if self._region_name:
                    kwargs['region_name'] = self._region_name
                self._client = boto3.client('cloudwatch', **kwargs)
            except Exception as exc:
                logger.warning('Failed to initialize boto3 CloudWatch client: %s', exc)
                self._client = None
        return self._client

    def emit_metric(
        self,
        name: str,
        value: float,
        unit: str = 'None',
        dimensions: dict[str, str] | None = None,
    ) -> bool:
        """
        Emit a single metric to CloudWatch.

        Args:
            name: Metric name (e.g., 'signal_generation_latency')
            value: Numeric value for the metric
            unit: CloudWatch unit (e.g., 'Seconds', 'Percent', 'Count')
            dimensions: Optional dict of dimension name -> value pairs

        Returns:
            True if emitted successfully, False otherwise
        """
        metric_data = {
            'MetricName': name,
            'Value': value,
            'Unit': unit,
        }

        if dimensions:
            metric_data['Dimensions'] = [
                {'Name': k, 'Value': str(v)} for k, v in dimensions.items()
            ]

        return self._put_metric(metric_data)

    def emit_signal_generation_latency(
        self,
        latency_seconds: float,
        strategy_id: str | None = None,
    ) -> bool:
        """Emit signal generation latency metric."""
        dimensions = {}
        if strategy_id:
            dimensions['Strategy'] = strategy_id
        return self.emit_metric(
            name=METRIC_SIGNAL_GENERATION_LATENCY,
            value=latency_seconds,
            unit='Seconds',
            dimensions=dimensions if dimensions else None,
        )

    def emit_order_submission_latency(
        self,
        latency_seconds: float,
        mode: str = 'paper',
    ) -> bool:
        """Emit order submission latency metric."""
        return self.emit_metric(
            name=METRIC_ORDER_SUBMISSION_LATENCY,
            value=latency_seconds,
            unit='Seconds',
            dimensions={'Mode': mode},
        )

    def emit_data_freshness(self, age_seconds: float) -> bool:
        """Emit data freshness metric."""
        return self.emit_metric(
            name=METRIC_DATA_FRESHNESS_SECONDS,
            value=age_seconds,
            unit='Seconds',
            dimensions={'Service': 'polyclaw-ingestion'},
        )

    def emit_unrealized_pnl(self, pnl_usd: float) -> bool:
        """Emit unrealized PnL metric."""
        return self.emit_metric(
            name=METRIC_UNREALIZED_PNL,
            value=pnl_usd,
            unit='None',
            dimensions={'Service': 'polyclaw-risk'},
        )

    def emit_strategy_sharpe(
        self,
        sharpe: float,
        strategy_id: str | None = None,
    ) -> bool:
        """Emit 7-day Sharpe ratio metric."""
        dimensions: dict[str, str] = {'Service': 'polyclaw-strategy'}
        if strategy_id:
            dimensions['Strategy'] = strategy_id
        return self.emit_metric(
            name=METRIC_STRATEGY_SHARPE_7D,
            value=sharpe,
            unit='None',
            dimensions=dimensions,
        )

    def emit_reconciliation_error_rate(self, error_pct: float) -> bool:
        """Emit reconciliation error rate metric."""
        return self.emit_metric(
            name=METRIC_RECONCILIATION_ERROR_PCT,
            value=error_pct,
            unit='Percent',
            dimensions={'Service': 'polyclaw-reconciliation'},
        )

    def emit_order_fill_rate(self, fill_rate_pct: float) -> bool:
        """Emit order fill rate metric."""
        return self.emit_metric(
            name=METRIC_ORDER_FILL_RATE,
            value=fill_rate_pct,
            unit='Percent',
            dimensions={'Service': 'polyclaw-execution'},
        )

    def _put_metric(self, metric_data: dict[str, Any]) -> bool:
        """Internal helper to put a single metric datum."""
        if self.client is None:
            logger.debug(
                '[MetricsCollector] Would emit metric: %s = %s (%s)',
                metric_data['MetricName'],
                metric_data['Value'],
                metric_data['Unit'],
            )
            return False

        try:
            self.client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric_data],
            )
            return True
        except Exception as exc:
            logger.warning(
                'Failed to emit CloudWatch metric %s: %s',
                metric_data['MetricName'],
                exc,
            )
            return False
