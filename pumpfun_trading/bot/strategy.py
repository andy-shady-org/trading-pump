from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class TradingBotConfig:
    buy_amount_sol: float = 0.01
    take_profit: float = 1.5
    stop_loss: float = 0.85
    max_active_positions: int = 1
    max_positions_per_mint: int = 1
    min_market_cap_sol: float = 5.0
    max_buy_attempts_per_mint: int = 3
    min_balance_sol: float = 0.05
    min_sell_balance: int = 1
    recent_token_ttl_seconds: int = 600
    reconnect_delay_seconds: float = 2.0
    dry_run: bool = False
    paper_trade: bool = False
    verbose: bool = True
    stream_url: str = "wss://pumpportal.fun/api/data"
    api_base_url: str = "https://frontend-api-v3.pump.fun"
    strategy_preset: str = "balanced"
    max_total_exposure_sol: float = 0.25
    max_position_size_sol: float = 0.05
    max_token_concentration_pct: float = 0.35
    max_loss_per_trade_sol: float = 0.02
    max_daily_drawdown_pct: float = 0.2
    reserve_balance_sol: float = 0.1
    health_check_timeout_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "buy_amount_sol": self.buy_amount_sol,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "max_active_positions": self.max_active_positions,
            "max_positions_per_mint": self.max_positions_per_mint,
            "min_market_cap_sol": self.min_market_cap_sol,
            "max_buy_attempts_per_mint": self.max_buy_attempts_per_mint,
            "min_balance_sol": self.min_balance_sol,
            "min_sell_balance": self.min_sell_balance,
            "recent_token_ttl_seconds": self.recent_token_ttl_seconds,
            "reconnect_delay_seconds": self.reconnect_delay_seconds,
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "verbose": self.verbose,
            "stream_url": self.stream_url,
            "api_base_url": self.api_base_url,
            "strategy_preset": self.strategy_preset,
            "max_total_exposure_sol": self.max_total_exposure_sol,
            "max_position_size_sol": self.max_position_size_sol,
            "max_token_concentration_pct": self.max_token_concentration_pct,
            "max_loss_per_trade_sol": self.max_loss_per_trade_sol,
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "reserve_balance_sol": self.reserve_balance_sol,
            "health_check_timeout_seconds": self.health_check_timeout_seconds,
        }

    @classmethod
    def from_file(cls, path: str | Path) -> "TradingBotConfig":
        config_path = Path(path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Config file {config_path} must contain a JSON object.")
        preset = str(raw.get("strategy_preset") or raw.get("preset") or "balanced")
        resolved = resolve_strategy_config(preset, overrides={k: v for k, v in raw.items() if k not in {"preset", "strategy_preset"}})
        return resolved


def resolve_strategy_config(
    preset: str = "balanced",
    *,
    overrides: dict[str, Any] | None = None,
) -> TradingBotConfig:
    preset_key = preset.lower()
    base = DEFAULT_PRESETS.get(preset_key, DEFAULT_PRESETS["balanced"]).copy()
    if overrides:
        base.update({k: v for k, v in overrides.items() if v is not None})

    config = TradingBotConfig(
        buy_amount_sol=float(base["buy_amount_sol"]),
        take_profit=float(base["take_profit"]),
        stop_loss=float(base["stop_loss"]),
        max_active_positions=int(base["max_active_positions"]),
        min_market_cap_sol=float(base["min_market_cap_sol"]),
        max_buy_attempts_per_mint=int(base["max_buy_attempts_per_mint"]),
        min_balance_sol=float(base["min_balance_sol"]),
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
        raise ValueError("stop_loss must be less than take_profit and both must be greater than zero.")
    if config.max_active_positions < 1:
        raise ValueError("max_active_positions must be at least 1.")
    return config


class TradingStrategy:
    def __init__(self, config: TradingBotConfig):
        self.config = config

    def should_buy(self, *, market_cap_sol: float, active_positions: int, mint_seen_recently: bool, buy_attempts: int) -> bool:
        return (
            not mint_seen_recently
            and active_positions < self.config.max_active_positions
            and market_cap_sol >= self.config.min_market_cap_sol
            and buy_attempts < self.config.max_buy_attempts_per_mint
        )

    def should_sell(self, *, performance: float, token_balance: int) -> bool:
        return token_balance > self.config.min_sell_balance and (
            performance >= self.config.take_profit or performance <= self.config.stop_loss
        )

    def summary(self) -> dict[str, Any]:
        return {
            "preset": self.config.strategy_preset,
            "buy_amount_sol": self.config.buy_amount_sol,
            "take_profit": self.config.take_profit,
            "stop_loss": self.config.stop_loss,
            "max_active_positions": self.config.max_active_positions,
            "min_market_cap_sol": self.config.min_market_cap_sol,
            "max_buy_attempts_per_mint": self.config.max_buy_attempts_per_mint,
            "min_balance_sol": self.config.min_balance_sol,
            "max_total_exposure_sol": self.config.max_total_exposure_sol,
            "max_position_size_sol": self.config.max_position_size_sol,
            "max_token_concentration_pct": self.config.max_token_concentration_pct,
            "max_loss_per_trade_sol": self.config.max_loss_per_trade_sol,
            "max_daily_drawdown_pct": self.config.max_daily_drawdown_pct,
            "reserve_balance_sol": self.config.reserve_balance_sol,
            "health_check_timeout_seconds": self.config.health_check_timeout_seconds,
        }


__all__ = ["DEFAULT_PRESETS", "TradingBotConfig", "TradingStrategy", "resolve_strategy_config"]
