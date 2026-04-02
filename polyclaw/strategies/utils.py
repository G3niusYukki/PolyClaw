"""Shared utilities for trading strategies."""


def calculate_liquidity_depth(liquidity_usd: float) -> float:
    """Calculate effective liquidity depth based on tier thresholds.

    Tiers:
    - Tier 1 (>= $10k): Full liquidity
    - Tier 2 ($3k-$10k): 70% weight
    - Tier 3 ($1k-$3k): 30% weight
    - Tier 4 (< $1k): 0%
    """
    if liquidity_usd >= 10000:
        return liquidity_usd
    elif liquidity_usd >= 3000:
        return liquidity_usd * 0.7
    elif liquidity_usd >= 1000:
        return liquidity_usd * 0.3
    else:
        return 0.0
