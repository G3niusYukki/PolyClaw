"""Retry decorator with exponential backoff for CTF operations."""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from typing import Any, Callable, TypeVar, ParamSpec

import httpx

logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class RetryableError(Exception):
    """Base class for errors that should trigger a retry."""
    pass


class NonRetryableError(Exception):
    """Base class for errors that should NOT trigger a retry."""
    pass


class InsufficientBalanceError(NonRetryableError):
    """Raised when the wallet has insufficient balance for the operation."""
    pass


class MarketClosedError(NonRetryableError):
    """Raised when attempting to trade on a closed market."""
    pass


def _is_retryable(exc: BaseException) -> bool:
    """Determine if an exception is retryable."""
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # 429 Too Many Requests
        if exc.response.status_code == 429:
            return True
        # 5xx server errors
        if 500 <= exc.response.status_code < 600:
            return True
        return False
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, NonRetryableError):
        return False
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return False
    # Unknown errors: retry by default
    return True


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator that retries a function with exponential backoff on retryable errors.

    Args:
        max_attempts: Maximum number of retry attempts (default 3).
        base_delay: Initial delay in seconds (default 1.0).
        max_delay: Maximum delay in seconds (default 30.0).
        exponential_base: Base for exponential backoff (default 2.0).

    Retryable errors:
        - httpx.ConnectError: Network connection failures
        - httpx.TimeoutException: Request timeouts
        - 429 rate limit responses
        - 5xx server errors

    Non-retryable errors:
        - ValueError, TypeError, KeyError
        - InsufficientBalanceError
        - MarketClosedError
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            attempt = 0
            last_exception: BaseException | None = None

            while attempt < max_attempts:
                try:
                    return fn(*args, **kwargs)
                except NonRetryableError:
                    # Don't retry non-retryable errors
                    raise
                except Exception as exc:  # noqa: BLE001
                    if not _is_retryable(exc):
                        logger.debug(
                            "Non-retryable error in %s (attempt %d/%d): %s",
                            fn.__name__,
                            attempt + 1,
                            max_attempts,
                            exc,
                        )
                        raise

                    last_exception = exc
                    attempt += 1

                    if attempt >= max_attempts:
                        logger.error(
                            "All %d attempts failed for %s. Last error: %s",
                            max_attempts,
                            fn.__name__,
                            exc,
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    logger.warning(
                        "Retryable error in %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs.",
                        fn.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"All {max_attempts} attempts failed for {fn.__name__}")

        @functools.wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            attempt = 0
            last_exception: BaseException | None = None

            while attempt < max_attempts:
                try:
                    return await fn(*args, **kwargs)  # type: ignore[operator]
                except NonRetryableError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if not _is_retryable(exc):
                        raise

                    last_exception = exc
                    attempt += 1

                    if attempt >= max_attempts:
                        logger.error(
                            "All %d attempts failed for %s. Last error: %s",
                            max_attempts,
                            fn.__name__,
                            exc,
                        )
                        raise

                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    logger.warning(
                        "Retryable error in %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs.",
                        fn.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception
            raise RuntimeError(f"All {max_attempts} attempts failed for {fn.__name__}")

        # Return async wrapper if the function is async, otherwise sync wrapper
        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return wrapper  # type: ignore[return-value]

    return decorator
