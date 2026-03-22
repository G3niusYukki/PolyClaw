"""Alert System — severity levels, alert data model, routing, and channel integrations."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from polyclaw.timeutils import utcnow

if TYPE_CHECKING:
    from polyclaw.monitoring.channels import ChannelResponse

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels, ordered from lowest to highest urgency."""
    INFO = 'INFO'
    WARNING = 'WARNING'
    CRITICAL = 'CRITICAL'


@dataclass
class Alert:
    """
    Represents a monitoring alert to be routed to one or more channels.

    Attributes:
        severity: Alert severity level (INFO, WARNING, CRITICAL)
        title: Short, descriptive title for the alert
        message: Detailed message describing the alert
        channels: List of channel names to route this alert to (e.g., ['telegram', 'pagerduty'])
        timestamp: When the alert was created (defaults to current UTC time)
        metadata: Additional context as key-value pairs
    """
    severity: AlertSeverity
    title: str
    message: str
    channels: list[str] = field(default_factory=lambda: ['telegram'])
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert alert to a serializable dictionary."""
        return {
            'severity': self.severity.value,
            'title': self.title,
            'message': self.message,
            'channels': self.channels,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata,
        }


class AlertRouter:
    """
    Routes alerts to configured notification channels.

    Supports multiple channels (Telegram, PagerDuty) with graceful degradation
    when channels are not configured.

    Example:
        router = AlertRouter()
        router.send(Alert(
            severity=AlertSeverity.CRITICAL,
            title='Portfolio PnL Alert',
            message='Unrealized PnL dropped below -$500',
            channels=['telegram', 'pagerduty'],
            metadata={'pnl': -512.34},
        ))
    """

    def __init__(
        self,
        telegram_channel: 'TelegramChannel | None' = None,
        pagerduty_channel: 'PagerDutyChannel | None' = None,
    ):
        """
        Initialize the alert router with channel instances.

        Args:
            telegram_channel: Telegram notification channel (lazy-loaded if not provided)
            pagerduty_channel: PagerDuty notification channel (lazy-loaded if not provided)
        """
        self._telegram = telegram_channel
        self._pagerduty = pagerduty_channel

    @property
    def telegram(self) -> 'TelegramChannel':
        """Lazy-load Telegram channel."""
        if self._telegram is None:
            from polyclaw.monitoring.channels import TelegramChannel
            self._telegram = TelegramChannel()
        return self._telegram

    @property
    def pagerduty(self) -> 'PagerDutyChannel':
        """Lazy-load PagerDuty channel."""
        if self._pagerduty is None:
            from polyclaw.monitoring.channels import PagerDutyChannel
            self._pagerduty = PagerDutyChannel()
        return self._pagerduty

    def send(self, alert: Alert) -> dict[str, 'ChannelResponse']:
        """
        Route an alert to all configured channels.

        Args:
            alert: The Alert to route

        Returns:
            dict mapping channel name to ChannelResponse
        """
        results: dict[str, 'ChannelResponse'] = {}

        for channel_name in alert.channels:
            if channel_name == 'telegram':
                results['telegram'] = self.telegram.send(
                    title=alert.title,
                    message=alert.message,
                    severity=alert.severity.value,
                    metadata=alert.metadata,
                )
            elif channel_name == 'pagerduty':
                results['pagerduty'] = self.pagerduty.send(
                    title=alert.title,
                    message=alert.message,
                    severity=alert.severity.value,
                    metadata=alert.metadata,
                )
            else:
                logger.warning('[AlertRouter] Unknown channel: %s', channel_name)
                continue

            # Log send results
            resp = results[channel_name]
            if resp.success:
                logger.info('[AlertRouter] Alert sent to %s: %s', channel_name, alert.title)
            else:
                logger.warning(
                    '[AlertRouter] Failed to send alert to %s (%s): %s',
                    channel_name,
                    resp.error,
                    alert.title,
                )

        return results

    def send_critical(self, title: str, message: str, **metadata) -> dict[str, 'ChannelResponse']:
        """Convenience method to send a CRITICAL alert to all configured channels."""
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            title=title,
            message=message,
            channels=['telegram', 'pagerduty'],
            metadata=metadata,
        )
        return self.send(alert)

    def send_warning(self, title: str, message: str, **metadata) -> dict[str, 'ChannelResponse']:
        """Convenience method to send a WARNING alert via Telegram."""
        alert = Alert(
            severity=AlertSeverity.WARNING,
            title=title,
            message=message,
            channels=['telegram'],
            metadata=metadata,
        )
        return self.send(alert)

    def send_info(self, title: str, message: str, **metadata) -> dict[str, 'ChannelResponse']:
        """Convenience method to send an INFO alert via Telegram."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            title=title,
            message=message,
            channels=['telegram'],
            metadata=metadata,
        )
        return self.send(alert)
