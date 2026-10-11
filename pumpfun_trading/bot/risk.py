"""Risk checks, exposure limits, and kill-switch validation for the bot runtime."""

from __future__ import annotations

from typing import Any


def check_risk_limits(
    bot: Any,
    *,
    mint: str,
    proposed_entry_sol: float,
    current_positions: dict[str, dict[str, Any]],
) -> bool:
    total_exposure = sum(
        float(pos.get("entry_market_cap", 0.0) or 0.0)
        for pos in current_positions.values()
    )
    if total_exposure + proposed_entry_sol > bot.config.max_total_exposure_sol:
        bot._last_event = (
            f"risk limit: max exposure {bot.config.max_total_exposure_sol:.2f} SOL"
        )
        return False
    if proposed_entry_sol > bot.config.max_position_size_sol:
        bot._last_event = (
            f"risk limit: position cap {bot.config.max_position_size_sol:.2f} SOL"
        )
        return False
    if mint in current_positions:
        bot._last_event = f"risk limit: mint already active {mint[:8]}..."
        return False

    if current_positions:
        max_per_token_ratio = (
            max(
                float(pos.get("entry_market_cap", 0.0) or 0.0)
                / bot.config.max_total_exposure_sol
                for pos in current_positions.values()
            )
            if bot.config.max_total_exposure_sol > 0
            else 0.0
        )
        if max_per_token_ratio > float(
            getattr(bot.config, "max_token_concentration_pct", 0.35)
        ):
            bot._last_event = (
                "risk limit: per-token concentration cap reached "
                f"({max_per_token_ratio:.2%} > {float(getattr(bot.config, 'max_token_concentration_pct', 0.35)):.2%})"
            )
            return False

    return True


def check_daily_drawdown(bot: Any) -> bool:
    if not bot.active_positions:
        return True

    total_equity = sum(
        float(pos.get("entry_market_cap", 0.0) or 0.0)
        for pos in bot.active_positions.values()
    )
    if total_equity <= 0:
        return True

    drawdown = 1.0 - (
        sum(
            float(pos.get("current_market_cap", 0.0) or 0.0)
            for pos in bot.active_positions.values()
        )
        / total_equity
    )
    if drawdown > bot.config.max_daily_drawdown_pct:
        bot._last_event = (
            f"risk limit: daily drawdown {drawdown:.2%} exceeds "
            f"{bot.config.max_daily_drawdown_pct:.2%}"
        )
        return False
    return True


def check_loss_per_trade(
    bot: Any, *, mint: str, current_market_cap: float | None = None
) -> bool:
    position = bot.active_positions.get(mint)
    if position is None:
        return True

    if current_market_cap is None:
        current_market_cap = float(position.get("current_market_cap", 0.0) or 0.0)
    entry_market_cap = float(position.get("entry_market_cap", 0.0) or 0.0)
    if entry_market_cap <= 0:
        return True

    loss_ratio = 1.0 - (current_market_cap / entry_market_cap)
    if loss_ratio > bot.config.max_loss_per_trade_sol / bot.config.buy_amount_sol:
        bot._last_event = (
            f"risk limit: trade loss {loss_ratio:.2%} exceeds max "
            f"{bot.config.max_loss_per_trade_sol / bot.config.buy_amount_sol:.2%}"
        )
        return False
    return True
