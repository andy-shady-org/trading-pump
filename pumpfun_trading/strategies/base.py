from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        from pumpfun_trading.strategies.presets import resolve_strategy_config

        return resolve_strategy_config(
            preset,
            overrides={
                k: v for k, v in raw.items() if k not in {"preset", "strategy_preset"}
            },
        )


__all__ = ["TradingBotConfig"]
