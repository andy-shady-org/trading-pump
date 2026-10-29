"""Factories for the domain objects most tests need.

Each factory takes keyword overrides, so a test only states what matters to
it. (The pumpbot-era ``make_bot`` / ``make_position`` / ``make_pool_keys``
built the retired ``TradingBot`` runtime and Raydium pools.)
"""

from __future__ import annotations

from typing import Any

from trading_pump.market import PoolReading
from trading_pump.strategies.filters import ScreeningSettings


def make_screening(**overrides: Any) -> ScreeningSettings:
    """``ScreeningSettings`` with the defaults plus ``overrides``."""
    return ScreeningSettings(**overrides)


# A standard graduation: ~85 SOL against ~206M tokens, i.e. a market cap
# near 410.88 SOL on the curve basis (price x 1B tokens).
GRADUATION_BASE_RESERVE = 206_900_000_000_000
GRADUATION_QUOTE_RESERVE = 85_000_000_000


def make_reading(
    mint: str,
    *,
    at: float = 1_000.0,
    base: int = GRADUATION_BASE_RESERVE,
    quote: int = GRADUATION_QUOTE_RESERVE,
    scale: float = 1.0,
    pool: str | None = "Pool",
) -> PoolReading:
    """A pool reading; ``scale`` multiplies the price (more SOL, fewer tokens
    at the same constant product)."""
    if scale != 1.0:
        root = scale**0.5
        quote = int(quote * root)
        base = int(base / root)
    return PoolReading(
        mint=mint, at=at, base_reserve=base, quote_reserve=quote, pool=pool
    )
