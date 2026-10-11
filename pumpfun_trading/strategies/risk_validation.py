from __future__ import annotations

from typing import Mapping

from pumpfun_trading.strategies.base import TradingBotConfig


def validate_risk_limits(
    config: TradingBotConfig,
    *,
    current_positions: Mapping[str, object] | None,
    proposed_entry_sol: float,
    wallet_balance_sol: float | None = None,
) -> bool:
    if config.max_active_positions < 1:
        return False

    position_count = len(current_positions or {})
    if position_count >= config.max_active_positions:
        return False

    if wallet_balance_sol is not None:
        available_after_reserve = wallet_balance_sol - config.reserve_balance_sol
        if proposed_entry_sol > available_after_reserve:
            return False

    return True
