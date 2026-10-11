from __future__ import annotations

from pumpfun_trading.strategies.base import TradingBotConfig


def generate_buy_signal(
    config: TradingBotConfig,
    *,
    market_cap_sol: float,
    active_positions: int,
    mint_seen_recently: bool,
    buy_attempts: int,
) -> bool:
    return (
        not mint_seen_recently
        and active_positions < config.max_active_positions
        and market_cap_sol >= config.min_market_cap_sol
        and buy_attempts < config.max_buy_attempts_per_mint
    )
