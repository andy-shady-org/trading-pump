from __future__ import annotations

from pumpfun_trading.strategies.base import TradingBotConfig


def passes_market_cap_filter(
    config: TradingBotConfig, *, market_cap_sol: float
) -> bool:
    return market_cap_sol >= config.min_market_cap_sol


def token_is_recently_seen(
    config: TradingBotConfig, *, mint_seen_recently: bool
) -> bool:
    return bool(mint_seen_recently)


def buy_attempts_within_limit(config: TradingBotConfig, *, buy_attempts: int) -> bool:
    return buy_attempts < config.max_buy_attempts_per_mint


def token_is_eligible(
    config: TradingBotConfig,
    *,
    market_cap_sol: float,
    mint_seen_recently: bool,
    buy_attempts: int,
) -> bool:
    return (
        passes_market_cap_filter(config, market_cap_sol=market_cap_sol)
        and not token_is_recently_seen(config, mint_seen_recently=mint_seen_recently)
        and buy_attempts_within_limit(config, buy_attempts=buy_attempts)
    )
