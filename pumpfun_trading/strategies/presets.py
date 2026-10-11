from __future__ import annotations

from typing import Any

from pumpfun_trading.strategies.base import TradingBotConfig

DEFAULT_PRESETS: dict[str, dict[str, float | int]] = {
    "conservative": {
        "buy_amount_sol": 0.005,
        "take_profit": 1.35,
        "stop_loss": 0.9,
        "max_active_positions": 1,
        "min_market_cap_sol": 10.0,
        "max_buy_attempts_per_mint": 2,
        "min_balance_sol": 0.1,
        "max_total_exposure_sol": 0.12,
        "max_position_size_sol": 0.04,
        "max_token_concentration_pct": 0.25,
        "max_loss_per_trade_sol": 0.015,
        "max_daily_drawdown_pct": 0.15,
        "reserve_balance_sol": 0.15,
        "health_check_timeout_seconds": 60,
    },
    "balanced": {
        "buy_amount_sol": 0.01,
        "take_profit": 1.5,
        "stop_loss": 0.85,
        "max_active_positions": 1,
        "min_market_cap_sol": 5.0,
        "max_buy_attempts_per_mint": 3,
        "min_balance_sol": 0.05,
        "max_total_exposure_sol": 0.25,
        "max_position_size_sol": 0.05,
        "max_token_concentration_pct": 0.35,
        "max_loss_per_trade_sol": 0.02,
        "max_daily_drawdown_pct": 0.2,
        "reserve_balance_sol": 0.1,
        "health_check_timeout_seconds": 60,
    },
    "aggressive": {
        "buy_amount_sol": 0.02,
        "take_profit": 1.75,
        "stop_loss": 0.8,
        "max_active_positions": 2,
        "min_market_cap_sol": 2.5,
        "max_buy_attempts_per_mint": 4,
        "min_balance_sol": 0.02,
        "max_total_exposure_sol": 0.5,
        "max_position_size_sol": 0.08,
        "max_token_concentration_pct": 0.5,
        "max_loss_per_trade_sol": 0.03,
        "max_daily_drawdown_pct": 0.25,
        "reserve_balance_sol": 0.05,
        "health_check_timeout_seconds": 60,
    },
}


def resolve_strategy_config(
    preset: str = "balanced",
    *,
    overrides: dict[str, Any] | None = None,
) -> TradingBotConfig:
    preset_key = (preset or "balanced").lower()
    if preset_key not in DEFAULT_PRESETS:
        preset_key = "balanced"
    base = DEFAULT_PRESETS[preset_key].copy()
    if overrides:
        base.update({k: v for k, v in overrides.items() if v is not None})

    config = TradingBotConfig(
        buy_amount_sol=float(base["buy_amount_sol"]),
        take_profit=float(base["take_profit"]),
        stop_loss=float(base["stop_loss"]),
        max_active_positions=int(base["max_active_positions"]),
        max_positions_per_mint=int(base.get("max_positions_per_mint", 1)),
        min_market_cap_sol=float(base["min_market_cap_sol"]),
        max_buy_attempts_per_mint=int(base["max_buy_attempts_per_mint"]),
        min_balance_sol=float(base["min_balance_sol"]),
        min_sell_balance=int(base.get("min_sell_balance", 1)),
        recent_token_ttl_seconds=int(base.get("recent_token_ttl_seconds", 600)),
        reconnect_delay_seconds=float(base.get("reconnect_delay_seconds", 2.0)),
        dry_run=bool(base.get("dry_run", False)),
        paper_trade=bool(base.get("paper_trade", False)),
        verbose=bool(base.get("verbose", True)),
        stream_url=str(base.get("stream_url", "wss://pumpportal.fun/api/data")),
        api_base_url=str(base.get("api_base_url", "https://frontend-api-v3.pump.fun")),
        strategy_preset=preset_key,
        max_total_exposure_sol=float(base["max_total_exposure_sol"]),
        max_position_size_sol=float(base["max_position_size_sol"]),
        max_token_concentration_pct=float(base["max_token_concentration_pct"]),
        max_loss_per_trade_sol=float(base["max_loss_per_trade_sol"]),
        max_daily_drawdown_pct=float(base["max_daily_drawdown_pct"]),
        reserve_balance_sol=float(base["reserve_balance_sol"]),
        health_check_timeout_seconds=int(base["health_check_timeout_seconds"]),
    )
    if config.buy_amount_sol <= 0:
        raise ValueError("buy_amount_sol must be greater than zero.")
    if not 0 < config.stop_loss < config.take_profit:
        raise ValueError(
            "stop_loss must be less than take_profit and both must be greater than zero."
        )
    if config.max_active_positions < 1:
        raise ValueError("max_active_positions must be at least 1.")
    return config
