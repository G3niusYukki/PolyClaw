"""Tests for LLM response parser."""

import pytest

from polyclaw.llm.parser import LLMProbabilityEstimate, parse_probability_response


class TestParseProbabilityResponse:
    def test_valid_json_response(self):
        raw = '{"reasoning": "test", "probability_yes": 0.75, "confidence": 0.85, "key_factors": ["a", "b"]}'
        result = parse_probability_response(raw, 'market-1', 'gpt-4o')
        assert result is not None
        assert result.market_id == 'market-1'
        assert result.estimated_probability_yes == 0.75
        assert result.confidence == 0.85
        assert result.reasoning == 'test'
        assert result.key_factors == ['a', 'b']
        assert result.model == 'gpt-4o'

    def test_json_with_markdown_wrapper(self):
        raw = '```json\n{"reasoning": "ok", "probability_yes": 0.6, "confidence": 0.7, "key_factors": []}\n```'
        result = parse_probability_response(raw, 'm-2')
        assert result is not None
        assert result.estimated_probability_yes == 0.6

    def test_probability_clamped_low(self):
        raw = '{"reasoning": "x", "probability_yes": 0.001, "confidence": 0.5}'
        result = parse_probability_response(raw, 'm-3')
        assert result is not None
        assert result.estimated_probability_yes == 0.01

    def test_probability_clamped_high(self):
        raw = '{"reasoning": "x", "probability_yes": 1.5, "confidence": 0.5}'
        result = parse_probability_response(raw, 'm-4')
        assert result is not None
        assert result.estimated_probability_yes == 0.99

    def test_confidence_clamped(self):
        raw = '{"reasoning": "x", "probability_yes": 0.5, "confidence": 2.0}'
        result = parse_probability_response(raw, 'm-5')
        assert result is not None
        assert result.confidence == 1.0

    def test_missing_probability_returns_none(self):
        raw = '{"reasoning": "x", "confidence": 0.5}'
        result = parse_probability_response(raw, 'm-6')
        assert result is None

    def test_invalid_json_returns_none(self):
        result = parse_probability_response('not json', 'm-7')
        assert result is None

    def test_default_confidence_when_missing(self):
        raw = '{"reasoning": "x", "probability_yes": 0.5}'
        result = parse_probability_response(raw, 'm-8')
        assert result is not None
        assert result.confidence == 0.5

    def test_key_factors_string_converted(self):
        raw = '{"reasoning": "x", "probability_yes": 0.5, "confidence": 0.5, "key_factors": "single"}'
        result = parse_probability_response(raw, 'm-9')
        assert result is not None
        assert result.key_factors == ['single']
