from __future__ import annotations

from pumpfun_trading.strategies.base import TradingBotConfig


def should_exit_position(
    config: TradingBotConfig,
    *,
    performance: float,
    token_balance: int,
) -> bool:
    return token_balance > config.min_sell_balance and (
        performance >= config.take_profit or performance <= config.stop_loss
    )
