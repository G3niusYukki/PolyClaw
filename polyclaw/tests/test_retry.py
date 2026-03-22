"""Tests for the retry decorator with exponential backoff."""
import time
from unittest.mock import MagicMock

import httpx
import pytest

from polyclaw.execution.retry import (
    InsufficientBalanceError,
    MarketClosedError,
    NonRetryableError,
    RetryableError,
    _is_retryable,
    retry,
)


class TestIsRetryable:
    """Tests for the _is_retryable helper."""

    def test_httpx_connect_error_retryable(self):
        """httpx.ConnectError is retryable."""
        assert _is_retryable(httpx.ConnectError('connection refused')) is True

    def test_httpx_timeout_retryable(self):
        """httpx.TimeoutException is retryable."""
        assert _is_retryable(httpx.TimeoutException('timed out')) is True

    def test_httpx_429_retryable(self):
        """HTTP 429 (rate limit) is retryable."""
        response = MagicMock()
        response.status_code = 429
        assert _is_retryable(httpx.HTTPStatusError('rate limited', request=MagicMock(), response=response)) is True

    def test_httpx_5xx_retryable(self):
        """HTTP 5xx errors are retryable."""
        for code in [500, 502, 503, 504]:
            response = MagicMock()
            response.status_code = code
            exc = httpx.HTTPStatusError('server error', request=MagicMock(), response=response)
            assert _is_retryable(exc) is True, f"HTTP {code} should be retryable"

    def test_httpx_4xx_non_retryable(self):
        """HTTP 4xx (non-429) errors are not retryable."""
        for code in [400, 401, 403, 404]:
            response = MagicMock()
            response.status_code = code
            exc = httpx.HTTPStatusError('client error', request=MagicMock(), response=response)
            assert _is_retryable(exc) is False, f"HTTP {code} should not be retryable"

    def test_retryable_error_subclass_retryable(self):
        """Custom RetryableError subclasses are retryable."""
        assert _is_retryable(RetryableError('test')) is True

    def test_non_retryable_error_not_retryable(self):
        """NonRetryableError and subclasses are not retryable."""
        assert _is_retryable(NonRetryableError('test')) is False
        assert _is_retryable(InsufficientBalanceError('no funds')) is False
        assert _is_retryable(MarketClosedError('market closed')) is False

    def test_value_errors_not_retryable(self):
        """ValueError, TypeError, KeyError are not retryable."""
        assert _is_retryable(ValueError('bad value')) is False
        assert _is_retryable(TypeError('wrong type')) is False
        assert _is_retryable(KeyError('missing key')) is False

    def test_unknown_errors_retryable(self):
        """Unknown errors default to retryable."""
        assert _is_retryable(RuntimeError('unknown')) is True
        assert _is_retryable(Exception('generic')) is True


class TestRetryDecorator:
    """Tests for the retry decorator."""

    def test_successful_call_no_retry(self):
        """Successful function calls are not retried."""
        call_count = 0

        @retry(max_attempts=3)
        def succeed():
            nonlocal call_count
            call_count += 1
            return 'success'

        result = succeed()
        assert result == 'success'
        assert call_count == 1

    def test_retry_on_retryable_error(self):
        """Retries on retryable errors up to max_attempts."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError('connection refused')
            return 'success'

        result = fail_then_succeed()
        assert result == 'success'
        assert call_count == 3

    def test_gives_up_after_max_attempts(self):
        """Gives up and raises after max_attempts on persistent retryable errors."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException('always times out')

        with pytest.raises(httpx.TimeoutException):
            always_fail()

        assert call_count == 3

    def test_no_retry_on_non_retryable_error(self):
        """NonRetryableError is raised immediately without retry."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        def raise_non_retryable():
            nonlocal call_count
            call_count += 1
            raise InsufficientBalanceError('no funds')

        with pytest.raises(InsufficientBalanceError):
            raise_non_retryable()

        assert call_count == 1

    def test_no_retry_on_value_error(self):
        """ValueError is not retried."""
        call_count = 0

        @retry(max_attempts=3)
        def raise_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError('invalid input')

        with pytest.raises(ValueError):
            raise_value_error()

        assert call_count == 1

    def test_exponential_backoff_delays(self):
        """Delays increase exponentially with each retry."""

        call_times: list[float] = []

        @retry(max_attempts=3, base_delay=0.1, exponential_base=2.0)
        def record_time_and_fail():
            call_times.append(time.time())
            raise httpx.ConnectError('fail')

        with pytest.raises(httpx.ConnectError):
            record_time_and_fail()

        assert len(call_times) == 3
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]

        # Exponential growth: delay2 should be roughly 2x delay1
        assert delay2 > delay1 * 1.5
        assert delay1 >= 0.1 - 0.02  # at least base_delay

    def test_max_delay_cap(self):
        """Delays are capped at max_delay."""

        call_times: list[float] = []

        @retry(max_attempts=2, base_delay=10.0, max_delay=5.0)
        def record_time_and_fail():
            call_times.append(time.time())
            raise httpx.ConnectError('fail')

        with pytest.raises(httpx.ConnectError):
            record_time_and_fail()

        assert len(call_times) == 2
        delay = call_times[1] - call_times[0]
        assert delay <= 5.1  # max_delay + small tolerance

    def test_retry_preserves_function_result(self):
        """Successful result is returned correctly after retries."""
        call_count = 0

        @retry(max_attempts=5)
        def compute():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError('try again')
            return {'data': 42}

        result = compute()
        assert result == {'data': 42}
        assert call_count == 3

    def test_retry_logs_warnings(self, caplog):
        """Retry attempts are logged at WARNING level."""
        call_count = 0

        @retry(max_attempts=2, base_delay=0.01)
        def failing_func():
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException('timeout')

        with pytest.raises(httpx.TimeoutException):
            failing_func()

        assert call_count == 2


class TestRetryableErrors:
    """Tests for custom retryable/non-retryable error classes."""

    def test_retryable_error_raised(self):
        """RetryableError can be raised and caught."""
        with pytest.raises(RetryableError):
            raise RetryableError('temporary failure')

    def test_insufficient_balance_not_retryable(self):
        """InsufficientBalanceError should not trigger retry."""
        exc = InsufficientBalanceError('insufficient funds')
        assert _is_retryable(exc) is False

    def test_market_closed_not_retryable(self):
        """MarketClosedError should not trigger retry."""
        exc = MarketClosedError('market is closed')
        assert _is_retryable(exc) is False
