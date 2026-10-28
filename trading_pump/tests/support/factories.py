"""Factories for the domain objects most tests need.

Each factory takes keyword overrides, so a test only states what matters to
it. (The pumpbot-era ``make_bot`` / ``make_position`` / ``make_pool_keys``
built the retired ``TradingBot`` runtime and Raydium pools.)
"""

from __future__ import annotations

from typing import Any

from trading_pump.strategies.filters import ScreeningSettings


def make_screening(**overrides: Any) -> ScreeningSettings:
    """``ScreeningSettings`` with the defaults plus ``overrides``."""
    return ScreeningSettings(**overrides)
