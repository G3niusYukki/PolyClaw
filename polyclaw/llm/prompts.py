"""Prompt templates for LLM probability estimation."""

from polyclaw.domain import MarketSnapshot


def build_probability_prompt(market: MarketSnapshot) -> tuple[str, str]:
    """Build system and user prompts for probability estimation.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    system_prompt = """\
You are a calibrated probability forecaster specializing in prediction markets.
Your task is to estimate the probability that a given event will occur (resolve to YES).

Guidelines:
- Base your estimate on the information provided
- Consider base rates, similar historical events, and structural factors
- Be well-calibrated: your confidence should reflect genuine uncertainty
- Avoid anchoring on the current market price
- Provide your estimate as a probability between 0.01 and 0.99

You MUST respond with valid JSON in this exact format:
{
    "reasoning": "Your step-by-step reasoning for the probability estimate",
    "probability_yes": 0.XX,
    "confidence": 0.XX,
    "key_factors": ["factor1", "factor2", "factor3"]
}

Where:
- probability_yes: Your estimated probability of the event resolving YES (0.01 to 0.99)
- confidence: How confident you are in your estimate (0.0 to 1.0)
- key_factors: 3-5 key factors driving your estimate
"""

    # Format close date
    closes_str = 'Unknown'
    if market.closes_at:
        closes_str = market.closes_at.strftime('%Y-%m-%d %H:%M UTC')

    user_prompt = f"""\
Market: {market.title}

Description: {market.description}

Category: {market.category}
Current YES price: {market.yes_price:.2f} (implied probability: {market.yes_price:.0%})
Current NO price: {market.no_price:.2f}
24h Volume: ${market.volume_24h_usd:,.0f}
Liquidity: ${market.liquidity_usd:,.0f}
Closes at: {closes_str}

Estimate the probability that this market resolves to YES."""

    return system_prompt, user_prompt
