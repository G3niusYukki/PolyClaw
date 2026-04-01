"""Tests for the LLM client module."""

import json
import pytest

from polyclaw.llm.client import LLMClient, RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60)
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_calls=2, window_seconds=60)
        limiter.acquire()
        limiter.acquire()
        assert limiter.acquire() is False


class TestLLMClientJsonExtraction:
    def test_extract_plain_json(self):
        text = '{"probability_yes": 0.75, "confidence": 0.8}'
        result = LLMClient._extract_json(text)
        assert result == {'probability_yes': 0.75, 'confidence': 0.8}

    def test_extract_json_with_markdown_block(self):
        text = 'Here is my analysis:\n```json\n{"probability_yes": 0.6}\n```'
        result = LLMClient._extract_json(text)
        assert result == {'probability_yes': 0.6}

    def test_extract_json_with_plain_code_block(self):
        text = '```\n{"probability_yes": 0.4}\n```'
        result = LLMClient._extract_json(text)
        assert result == {'probability_yes': 0.4}

    def test_extract_json_with_surrounding_text(self):
        text = 'Some text before {"key": "value"} some text after'
        result = LLMClient._extract_json(text)
        assert result == {'key': 'value'}

    def test_extract_json_returns_none_on_failure(self):
        assert LLMClient._extract_json('not json at all') is None

    def test_no_api_key_raises(self):
        from polyclaw.config import Settings
        s = Settings(llm_api_key='', llm_provider='openai')
        import importlib
        import polyclaw.config as cfg
        old = cfg.settings
        cfg.settings = s
        try:
            client = LLMClient()
            with pytest.raises(ValueError, match='LLM_API_KEY'):
                client._get_client()
        finally:
            cfg.settings = old


class TestLLMClientComplete:
    def test_complete_returns_none_when_rate_limited(self, monkeypatch):
        from polyclaw.config import Settings
        import polyclaw.config as cfg
        old = cfg.settings
        cfg.settings = Settings(llm_api_key='test-key')
        try:
            client = LLMClient()
            # Exhaust rate limiter
            for _ in range(10):
                client._rate_limiter.acquire()
            result = client.complete('sys', 'user')
            assert result is None
        finally:
            cfg.settings = old
