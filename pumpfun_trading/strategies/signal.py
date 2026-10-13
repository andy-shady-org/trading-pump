from __future__ import annotations

from typing import Optional

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.copy_trading import CopyTradeSignal
from pumpfun_trading.strategies.graduation import GraduationSignal
from pumpfun_trading.strategies.momentum import MomentumSignal


def generate_buy_signal(
    config: TradingBotConfig,
    *,
    market_cap_sol: float,
    active_positions: int,
    mint_seen_recently: bool,
    buy_attempts: int,
    momentum_signal: Optional[MomentumSignal] = None,
) -> bool:
    basic_pass = (
        not mint_seen_recently
        and active_positions < config.max_active_positions
        and market_cap_sol >= config.min_market_cap_sol
        and buy_attempts < config.max_buy_attempts_per_mint
    )
    if not basic_pass:
        return False
    if momentum_signal is not None and config.enable_momentum_signals:
        return momentum_signal.triggered
    return True


def generate_momentum_buy_signal(
    config: TradingBotConfig,
    *,
    momentum_signal: MomentumSignal,
    active_positions: int,
    buy_attempts: int,
    mint_seen_recently: bool = False,
) -> bool:
    if not config.enable_momentum_signals:
        return False
    return (
        not mint_seen_recently
        and active_positions < config.max_active_positions
        and buy_attempts < config.max_buy_attempts_per_mint
        and momentum_signal.triggered
    )


def generate_graduation_buy_signal(
    config: TradingBotConfig,
    *,
    graduation_signal: GraduationSignal,
    active_positions: int,
    buy_attempts: int,
    mint_seen_recently: bool = False,
) -> bool:
    if not config.enable_raydium_migration_sniping:
        return False
    return (
        not mint_seen_recently
        and active_positions < config.max_active_positions
        and buy_attempts < config.max_buy_attempts_per_mint
        and graduation_signal.triggered
    )


def generate_copy_trade_buy_signal(
    config: TradingBotConfig,
    *,
    copy_trade_signal: CopyTradeSignal,
    active_positions: int,
    buy_attempts: int,
    mint_seen_recently: bool = False,
) -> bool:
    if not config.enable_copy_trading:
        return False
    return (
        not mint_seen_recently
        and active_positions < config.max_active_positions
        and buy_attempts < config.max_buy_attempts_per_mint
        and copy_trade_signal.triggered
        and copy_trade_signal.is_buy
    )


__all__ = [
    "generate_buy_signal",
    "generate_momentum_buy_signal",
    "generate_graduation_buy_signal",
    "generate_copy_trade_buy_signal",
]
