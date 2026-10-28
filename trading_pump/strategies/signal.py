from __future__ import annotations

from typing import Optional

from trading_pump.strategies.base import TradingBotConfig
from trading_pump.strategies.copy_trading import CopyTradeSignal
from trading_pump.strategies.graduation import GraduationSignal
from trading_pump.strategies.momentum import MomentumSignal


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
    token_age_seconds: float | None = None,
    market_cap_sol: float | None = None,
) -> bool:
    """Momentum entry; with ``token_age_seconds`` / ``market_cap_sol`` also the
    confirmed-entry window and band (FEAT-52)."""
    if not config.enable_momentum_signals:
        return False
    if token_age_seconds is not None and not (
        float(getattr(config, "momentum_min_token_age_seconds", 0.0))
        <= token_age_seconds
        <= float(config.momentum_max_token_age_seconds)
    ):
        return False
    if market_cap_sol is not None and not (
        float(config.min_market_cap_sol)
        <= market_cap_sol
        <= float(getattr(config, "momentum_max_market_cap_sol", float("inf")))
    ):
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
