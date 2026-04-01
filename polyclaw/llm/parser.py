"""LLM response parser for probability estimates."""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LLMProbabilityEstimate:
    """Parsed LLM probability estimate for a market."""

    market_id: str
    estimated_probability_yes: float
    confidence: float
    reasoning: str
    key_factors: list[str] = field(default_factory=list)
    model: str = ''
    raw_response: str = ''


def parse_probability_response(
    raw_response: str,
    market_id: str,
    model: str = '',
) -> LLMProbabilityEstimate | None:
    """Parse LLM response into a LLMProbabilityEstimate.

    Handles various response formats including markdown code blocks and extra text.
    Returns None if parsing fails or values are out of range.
    """
    parsed = _extract_json(raw_response)
    if parsed is None:
        logger.warning('Failed to parse LLM response for market %s', market_id)
        return None

    prob = parsed.get('probability_yes')
    confidence = parsed.get('confidence')
    reasoning = parsed.get('reasoning', '')
    key_factors = parsed.get('key_factors', [])

    # Validate probability
    if prob is None or not isinstance(prob, (int, float)):
        logger.warning('Missing or invalid probability_yes for market %s', market_id)
        return None

    # Clamp to [0.01, 0.99]
    prob = max(0.01, min(0.99, float(prob)))

    # Validate confidence
    if confidence is None or not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    # Validate key_factors
    if not isinstance(key_factors, list):
        key_factors = [str(key_factors)]
    key_factors = [str(f) for f in key_factors[:10]]

    return LLMProbabilityEstimate(
        market_id=market_id,
        estimated_probability_yes=prob,
        confidence=confidence,
        reasoning=str(reasoning),
        key_factors=key_factors,
        model=model,
        raw_response=raw_response,
    )


def _extract_json(text: str) -> dict | None:
    """Extract JSON dict from text, handling various formats."""
    text = text.strip()

    # Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Markdown code block
    for marker in ('```json', '```'):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.find('```', start)
            if end != -1:
                try:
                    result = json.loads(text[start:end].strip())
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    continue

    # First { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None
