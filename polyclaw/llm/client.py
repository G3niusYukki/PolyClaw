"""Unified LLM client supporting OpenAI and Anthropic providers."""

import json
import logging
import time
from typing import Any, cast

from polyclaw.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_calls: int = 10, window_seconds: int = 60) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._timestamps: list[float] = []

    def acquire(self) -> bool:
        """Return True if the call is allowed, False if rate limited."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self._max_calls:
            return False
        self._timestamps.append(now)
        return True


class LLMClient:
    """Unified client for OpenAI and Anthropic LLM APIs."""

    def __init__(self) -> None:
        self._provider = settings.llm_provider
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._max_tokens = settings.llm_max_tokens
        self._temperature = settings.llm_temperature
        self._rate_limiter = RateLimiter(max_calls=10, window_seconds=60)
        self._total_tokens = 0
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the underlying SDK client."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError('LLM_API_KEY is not configured')
        if self._provider == 'openai':
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        elif self._provider == 'anthropic':
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        else:
            raise ValueError(f'Unsupported LLM provider: {self._provider}')
        return self._client

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        """Send a prompt and return the raw text response.

        Returns None on failure (rate limit, API error, etc.).
        """
        if not self._rate_limiter.acquire():
            logger.warning('LLM rate limit reached, skipping call')
            return None

        for attempt in range(3):
            try:
                return self._call_api(system_prompt, user_prompt)
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning('LLM call attempt %d failed: %s (retry in %ds)', attempt + 1, exc, wait)
                if attempt < 2:
                    time.sleep(wait)
        logger.error('All LLM call attempts failed')
        return None

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        """Send a prompt and parse the response as JSON.

        Returns None on failure or if response is not valid JSON.
        """
        raw = self.complete(system_prompt, user_prompt)
        if raw is None:
            return None
        return self._extract_json(raw)

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Make the actual API call."""
        client = self._get_client()
        if self._provider == 'openai':
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
            usage = resp.usage
            if usage:
                self._total_tokens += usage.total_tokens
            return resp.choices[0].message.content or ''
        else:  # anthropic
            resp = client.messages.create(
                model=self._model,
                system=system_prompt,
                messages=[{'role': 'user', 'content': user_prompt}],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )
            self._total_tokens += resp.usage.input_tokens + resp.usage.output_tokens
            return cast(str, resp.content[0].text)

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try direct parse
        text = text.strip()
        try:
            return cast('dict[str, Any]', json.loads(text))
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code block
        for marker in ('```json', '```'):
            if marker in text:
                start = text.index(marker) + len(marker)
                end = text.find('```', start)
                if end != -1:
                    try:
                        return cast('dict[str, Any]', json.loads(text[start:end].strip()))
                    except json.JSONDecodeError:
                        continue
        # Try finding first { to last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            try:
                return cast('dict[str, Any]', json.loads(text[start:end + 1]))
            except json.JSONDecodeError:
                pass
        logger.warning('Failed to extract JSON from LLM response')
        return None

    @property
    def total_tokens(self) -> int:
        return self._total_tokens
