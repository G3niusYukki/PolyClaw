"""Alert Notification Channels — Telegram and PagerDuty integrations."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from polyclaw.config import settings

logger = logging.getLogger(__name__)

# Default timeout for HTTP requests to notification channels (seconds)
DEFAULT_TIMEOUT = 10


@dataclass
class ChannelResponse:
    """Result of sending a notification to a channel."""
    success: bool
    channel: str
    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None


class AlertChannel(ABC):
    """Abstract base class for alert notification channels."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this channel."""
        ...

    @abstractmethod
    def send(self, title: str, message: str, severity: str, metadata: dict | None = None) -> ChannelResponse:
        """
        Send an alert to this channel.

        Args:
            title: Alert title
            message: Alert message body
            severity: Alert severity level (INFO, WARNING, CRITICAL)
            metadata: Optional additional context

        Returns:
            ChannelResponse with success status and details
        """
        ...

    def _build_payload(self, title: str, message: str, severity: str, metadata: dict | None) -> dict:
        """Build a standardized payload for this channel."""
        base = {
            'title': title,
            'message': message,
            'severity': severity,
            'metadata': metadata or {},
        }
        return base


class TelegramChannel(AlertChannel):
    """
    Telegram Bot API notification channel.

    Requires bot_token and chat_id to be configured via settings or env vars.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        # Allow direct injection or fallback to settings
        self._bot_token = bot_token or getattr(settings, 'telegram_bot_token', None) or ''
        self._chat_id = chat_id or getattr(settings, 'telegram_chat_id', None) or ''
        self._timeout = timeout

    @property
    def name(self) -> str:
        return 'telegram'

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is properly configured."""
        return bool(self._bot_token and self._chat_id)

    def send(
        self,
        title: str,
        message: str,
        severity: str,
        metadata: dict | None = None,
    ) -> ChannelResponse:
        if not self.is_configured:
            logger.info(
                '[TelegramChannel] Not configured — bot_token or chat_id missing. '
                'Alert skipped: %s',
                title,
            )
            return ChannelResponse(
                success=False,
                channel=self.name,
                error='Not configured (bot_token or chat_id missing)',
            )

        # Build severity emoji indicator
        emoji_map = {
            'CRITICAL': '\u26a0\ufe0f CRITICAL',
            'WARNING': '\u26a0 WARNING',
            'INFO': '\u2139\ufe0f INFO',
        }
        emoji = emoji_map.get(severity, '\u2139\ufe0f')

        # Format message with HTML-style formatting for Telegram
        body = (
            f'{emoji} <b>{title}</b>\n\n'
            f'{message}\n\n'
            f'<code>Severity: {severity}</code>'
        )

        if metadata:
            meta_lines = '\n'.join(f'  {k}: {v}' for k, v in metadata.items())
            body += f'\n<code>{meta_lines}</code>'

        try:
            url = f'https://api.telegram.org/bot{self._bot_token}/sendMessage'
            response = requests.post(
                url,
                json={
                    'chat_id': self._chat_id,
                    'text': body,
                    'parse_mode': 'HTML',
                },
                timeout=self._timeout,
            )
            success = response.status_code == 200
            return ChannelResponse(
                success=success,
                channel=self.name,
                status_code=response.status_code,
                response_body=response.text[:200] if response.text else None,
                error=None if success else f'HTTP {response.status_code}',
            )
        except requests.RequestException as exc:
            logger.warning('[TelegramChannel] Failed to send message: %s', exc)
            return ChannelResponse(
                success=False,
                channel=self.name,
                error=str(exc),
            )


class PagerDutyChannel(AlertChannel):
    """
    PagerDuty Events API v2 notification channel.

    Requires integration_key to be configured via settings or env vars.
    """

    # PagerDuty API endpoint
    PAGERDUTY_URL = 'https://events.pagerduty.com/v2/enqueue'

    # Map our severity to PagerDuty severity
    SEVERITY_MAP = {
        'CRITICAL': 'critical',
        'WARNING': 'warning',
        'INFO': 'info',
    }

    def __init__(
        self,
        integration_key: str | None = None,
        routing_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        # Allow direct injection or fallback to settings
        self._integration_key = (
            integration_key
            or routing_key
            or getattr(settings, 'pagerduty_integration_key', None)
            or ''
        )
        self._timeout = timeout

    @property
    def name(self) -> str:
        return 'pagerduty'

    @property
    def is_configured(self) -> bool:
        """Check if PagerDuty is properly configured."""
        return bool(self._integration_key)

    def send(
        self,
        title: str,
        message: str,
        severity: str,
        metadata: dict | None = None,
    ) -> ChannelResponse:
        if not self.is_configured:
            logger.info(
                '[PagerDutyChannel] Not configured — integration_key missing. '
                'Alert skipped: %s',
                title,
            )
            return ChannelResponse(
                success=False,
                channel=self.name,
                error='Not configured (integration_key missing)',
            )

        pd_severity = self.SEVERITY_MAP.get(severity, 'info')

        payload = {
            'routing_key': self._integration_key,
            'event_action': 'trigger',
            'dedup_key': f'polyclaw-{title[:64]}',
            'payload': {
                'summary': f'{title}: {message}',
                'source': 'PolyClaw',
                'severity': pd_severity,
                'custom_details': {
                    'message': message,
                    'severity': severity,
                    **(metadata or {}),
                },
            },
        }

        try:
            response = requests.post(
                self.PAGERDUTY_URL,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=self._timeout,
            )
            success = response.status_code in (200, 202, 201)
            return ChannelResponse(
                success=success,
                channel=self.name,
                status_code=response.status_code,
                response_body=response.text[:200] if response.text else None,
                error=None if success else f'HTTP {response.status_code}',
            )
        except requests.RequestException as exc:
            logger.warning('[PagerDutyChannel] Failed to send alert: %s', exc)
            return ChannelResponse(
                success=False,
                channel=self.name,
                error=str(exc),
            )
