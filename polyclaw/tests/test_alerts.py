"""Tests for alert routing and notification channels."""

import pytest
import requests
from unittest.mock import patch, MagicMock

from polyclaw.monitoring.alerts import Alert, AlertRouter, AlertSeverity
from polyclaw.monitoring.channels import ChannelResponse, PagerDutyChannel, TelegramChannel


class TestAlertSeverity:
    """Tests for AlertSeverity enum."""

    def test_severity_values(self):
        assert AlertSeverity.INFO.value == 'INFO'
        assert AlertSeverity.WARNING.value == 'WARNING'
        assert AlertSeverity.CRITICAL.value == 'CRITICAL'


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_defaults(self):
        alert = Alert(
            severity=AlertSeverity.WARNING,
            title='Test Alert',
            message='Something went wrong',
        )
        assert alert.severity == AlertSeverity.WARNING
        assert alert.title == 'Test Alert'
        assert alert.message == 'Something went wrong'
        assert alert.channels == ['telegram']
        from datetime import datetime
        assert isinstance(alert.timestamp, datetime)

    def test_alert_to_dict(self):
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            title='Portfolio Loss',
            message='PnL dropped below threshold',
            channels=['telegram', 'pagerduty'],
            metadata={'pnl': -600.0},
        )
        d = alert.to_dict()
        assert d['severity'] == 'CRITICAL'
        assert d['title'] == 'Portfolio Loss'
        assert d['channels'] == ['telegram', 'pagerduty']
        assert d['metadata']['pnl'] == -600.0


class TestTelegramChannel:
    """Tests for TelegramChannel."""

    def test_is_configured_false_when_empty(self):
        ch = TelegramChannel(bot_token='', chat_id='')
        assert ch.is_configured is False

    def test_is_configured_true_when_provided(self):
        ch = TelegramChannel(bot_token='123456:ABC-DEF', chat_id='987654321')
        assert ch.is_configured is True

    def test_send_when_not_configured(self):
        ch = TelegramChannel(bot_token='', chat_id='')
        resp = ch.send('Test', 'Test message', 'INFO')
        assert resp.success is False
        assert 'not configured' in resp.error.lower()

    def test_send_success(self):
        ch = TelegramChannel(bot_token='123456:ABC-DEF', chat_id='987654321')
        with patch('polyclaw.monitoring.channels.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = 'ok'
            mock_post.return_value = mock_response

            resp = ch.send('Test Alert', 'Test body', 'WARNING')

            assert resp.success is True
            assert resp.channel == 'telegram'
            assert resp.status_code == 200
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args.kwargs['json']['chat_id'] == '987654321'
            assert 'Test Alert' in call_args.kwargs['json']['text']

    def test_send_failure(self):
        ch = TelegramChannel(bot_token='123456:ABC-DEF', chat_id='987654321')
        with patch('polyclaw.monitoring.channels.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.text = 'Bad Request'
            mock_post.return_value = mock_response

            resp = ch.send('Test', 'Body', 'CRITICAL')
            assert resp.success is False
            assert resp.status_code == 400

    def test_send_network_error(self):
        ch = TelegramChannel(bot_token='123456:ABC-DEF', chat_id='987654321')
        with patch('polyclaw.monitoring.channels.requests.post') as mock_post:
            mock_post.side_effect = requests.RequestException('Connection refused')
            resp = ch.send('Test', 'Body', 'INFO')
            assert resp.success is False
            assert 'Connection refused' in resp.error


class TestPagerDutyChannel:
    """Tests for PagerDutyChannel."""

    def test_is_configured_false_when_empty(self):
        ch = PagerDutyChannel(integration_key='')
        assert ch.is_configured is False

    def test_is_configured_true_when_provided(self):
        ch = PagerDutyChannel(integration_key='abcd1234efgh5678')
        assert ch.is_configured is True

    def test_send_when_not_configured(self):
        ch = PagerDutyChannel(integration_key='')
        resp = ch.send('Test', 'Test message', 'WARNING')
        assert resp.success is False
        assert 'not configured' in resp.error.lower()

    def test_send_success(self):
        ch = PagerDutyChannel(integration_key='abcd1234efgh5678')
        with patch('polyclaw.monitoring.channels.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 202
            mock_response.text = '{"status": "success"}'
            mock_post.return_value = mock_response

            resp = ch.send('Critical Alert', 'Portfolio loss', 'CRITICAL', {'pnl': -600})

            assert resp.success is True
            assert resp.channel == 'pagerduty'
            assert resp.status_code == 202
            call_args = mock_post.call_args
            assert call_args.kwargs['json']['routing_key'] == 'abcd1234efgh5678'
            assert call_args.kwargs['json']['event_action'] == 'trigger'
            assert call_args.kwargs['json']['payload']['severity'] == 'critical'


class TestAlertRouter:
    """Tests for AlertRouter."""

    def test_send_to_telegram_only(self):
        telegram = TelegramChannel(bot_token='123456:ABC-DEF', chat_id='987654321')
        router = AlertRouter(telegram_channel=telegram)
        alert = Alert(
            severity=AlertSeverity.INFO,
            title='Test',
            message='Test message',
            channels=['telegram'],
        )

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            results = router.send(alert)
            assert 'telegram' in results
            assert results['telegram'].success is True

    def test_send_to_multiple_channels(self):
        telegram = TelegramChannel(bot_token='123', chat_id='456')
        pagerduty = PagerDutyChannel(integration_key='key123')
        router = AlertRouter(telegram_channel=telegram, pagerduty_channel=pagerduty)
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            title='Critical Alert',
            message='Something bad happened',
            channels=['telegram', 'pagerduty'],
        )

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            with patch.object(pagerduty, 'send', return_value=ChannelResponse(success=True, channel='pagerduty', status_code=202)):
                results = router.send(alert)
                assert 'telegram' in results
                assert 'pagerduty' in results

    def test_unknown_channel_skipped(self):
        telegram = TelegramChannel(bot_token='123', chat_id='456')
        router = AlertRouter(telegram_channel=telegram)
        alert = Alert(
            severity=AlertSeverity.INFO,
            title='Test',
            message='Test',
            channels=['telegram', 'slack'],
        )

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            results = router.send(alert)
            assert 'telegram' in results
            assert 'slack' not in results

    def test_send_critical_convenience(self):
        telegram = TelegramChannel(bot_token='123', chat_id='456')
        router = AlertRouter(telegram_channel=telegram)

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            results = router.send_critical('Portfolio Loss', 'PnL below -$500', pnl=-512)
            assert 'telegram' in results

    def test_send_warning_convenience(self):
        telegram = TelegramChannel(bot_token='123', chat_id='456')
        router = AlertRouter(telegram_channel=telegram)

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            results = router.send_warning('High Slippage', 'Avg slippage > 0.5%')
            assert 'telegram' in results

    def test_send_info_convenience(self):
        telegram = TelegramChannel(bot_token='123', chat_id='456')
        router = AlertRouter(telegram_channel=telegram)

        with patch.object(telegram, 'send', return_value=ChannelResponse(success=True, channel='telegram', status_code=200)):
            results = router.send_info('Daily Report', 'Report generated')
            assert 'telegram' in results
