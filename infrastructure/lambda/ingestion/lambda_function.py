"""Lambda handler for scheduled PolyClaw historical data ingestion.

This handler is triggered by EventBridge on a 3-minute schedule to
fetch the latest market data from Polymarket and persist it to the
database.
"""

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from polyclaw.db import SessionLocal
from polyclaw.ingestion import BackfillRunner

# Structured logger for CloudWatch
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _configure_logging(correlation_id: str) -> None:
    """Reconfigure root logger with structured fields."""
    class StructuredFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            record.correlation_id = correlation_id
            return (
                f"[%(asctime)s] %(levelname)s "
                f"[correlation_id=%(correlation_id)s] "
                f"[%(name)s] %(message)s"
            )

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


@contextmanager
def _db_session():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def lambda_handler(event: dict, context) -> dict:
    """AWS Lambda entry point.

    Args:
        event: Lambda event (from EventBridge scheduled event).
        context: Lambda context object.

    Returns:
        Dict with statusCode and body for API Gateway/Lambda proxy integration.
    """
    correlation_id = str(uuid.uuid4())
    _configure_logging(correlation_id)

    start_time = time.time()

    logger.info(
        "Ingestion Lambda started",
        extra={
            'event_id': event.get('id', 'unknown'),
            'detail_type': event.get('detail-type', 'Scheduled Event'),
        },
    )

    # Emit CloudWatch metric for Lambda invocation
    _emit_metric('IngestionInvocations', 1, 'Count')

    try:
        with _db_session() as session:
            runner = BackfillRunner(session=session)
            result = runner.fetch_markets_snapshot(limit=100, closed=False)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Ingestion Lambda completed",
            extra={
                'markets_fetched': len(result),
                'duration_ms': round(duration_ms, 2),
            },
        )

        _emit_metric('IngestionDuration', duration_ms, 'Milliseconds')
        _emit_metric('IngestionMarkets', len(result), 'Count')

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'ok',
                'correlation_id': correlation_id,
                'markets_fetched': len(result),
                'duration_ms': round(duration_ms, 2),
            }),
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.exception(
            "Ingestion Lambda failed",
            extra={
                'duration_ms': round(duration_ms, 2),
                'error': str(e),
            },
        )
        _emit_metric('IngestionErrors', 1, 'Count')

        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'correlation_id': correlation_id,
                'error': str(e),
            }),
        }


def _emit_metric(name: str, value: float, unit: str) -> None:
    """Emit a CloudWatch custom metric.

    In production, this uses boto3 client. In local/testing,
    this is a no-op to avoid import errors.
    """
    try:
        import boto3
        client = boto3.client('cloudwatch', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        client.put_metric_data(
            Namespace='PolyClaw/Ingestion',
            MetricData=[{
                'MetricName': name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.utcnow(),
            }],
        )
    except Exception:
        # Silently skip metric emission if boto3 not available or credentials missing
        pass
