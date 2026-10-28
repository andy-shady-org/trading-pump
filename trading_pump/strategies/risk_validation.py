from __future__ import annotations

from typing import Mapping

from trading_pump.strategies.base import TradingBotConfig


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

    # Same capital caps as the live bot's `check_risk_limits` (BUG-78).
    from trading_pump.bot.risk import (
        _extract_position_cost,
        _extract_position_fraction,
    )

    proposed = float(proposed_entry_sol)
    max_position = float(getattr(config, "max_position_size_sol", 0.0) or 0.0)
    if max_position > 0 and proposed > max_position:
        return False

    default_cost = float(getattr(config, "buy_amount_sol", 0.0) or 0.0)
    open_costs = [
        _extract_position_cost(pos, default_cost) * _extract_position_fraction(pos)
        for pos in (current_positions or {}).values()
    ]
    max_exposure = float(getattr(config, "max_total_exposure_sol", 0.0) or 0.0)
    if max_exposure > 0:
        if sum(open_costs) + proposed > max_exposure:
            return False
        max_concentration = float(
            getattr(config, "max_token_concentration_pct", 0.0) or 0.0
        )
        if (
            max_concentration > 0
            and max(open_costs + [proposed]) / max_exposure > max_concentration
        ):
            return False

    return True
