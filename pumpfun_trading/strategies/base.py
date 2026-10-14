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
    stream_url: str = "http://127.0.0.1:10000"
    api_base_url: str = "https://frontend-api-v3.pump.fun"
    strategy_preset: str = "balanced"
    max_total_exposure_sol: float = 0.25
    max_position_size_sol: float = 0.05
    max_token_concentration_pct: float = 0.35
    max_loss_per_trade_sol: float = 0.02
    max_daily_drawdown_pct: float = 0.2
    reserve_balance_sol: float = 0.1
    health_check_timeout_seconds: int = 60
    emergency_hard_lock_hours: float = 24.0
    auto_liquidate_on_circuit_breaker: bool = True
    enable_trailing_stop: bool = True
    trailing_stop_activation_pct: float = 0.50
    trailing_stop_drop_pct: float = 0.15
    enable_stagnant_exit: bool = True
    stagnant_timeout_seconds: float = 120.0
    enable_max_hold_timeout: bool = True
    max_hold_time_seconds: float = 600.0
    stagnant_price_delta_threshold_pct: float = 0.005
    enable_tiered_take_profit: bool = True
    tier_1_take_profit: float = 2.0
    tier_1_sell_fraction: float = 0.50
    tier_2_take_profit: float = 3.5
    tier_2_sell_fraction: float = 0.25
    moonbag_trailing_floor: float = 2.5
    enable_anti_rug_filters: bool = True
    max_dev_24h_launches: int = 5
    max_creator_initial_holding_pct: float = 0.10
    max_top5_holder_concentration_pct: float = 0.15
    max_gini_coefficient: float = 0.85
    require_social_links: bool = False
    min_social_links_count: int = 1
    max_acceptable_risk_score: float = 50.0
    screening_cache_ttl_seconds: int = 60
    enable_momentum_signals: bool = True
    momentum_window_seconds: int = 30
    momentum_min_buy_ratio: float = 3.0
    momentum_min_z_score: float = 2.5
    momentum_min_unique_buyers: int = 3
    momentum_min_net_inflow_sol: float = 0.5
    momentum_baseline_window_seconds: int = 300
    momentum_max_token_age_seconds: int = 1800
    enable_raydium_migration_sniping: bool = True
    raydium_pre_migration_sol_threshold: float = 80.0
    raydium_buy_amount_sol: float = 0.02
    raydium_slippage_bps: int = 500
    raydium_priority_fee_lamports: int = 100_000
    raydium_max_entry_latency_seconds: float = 30.0
    enable_copy_trading: bool = True
    copy_trading_wallets: tuple[dict[str, Any], ...] = ()
    copy_trading_sizing_mode: str = "proportional"
    copy_trading_scale_factor: float = 1.0
    copy_trading_min_wallet_win_rate: float = 0.60
    copy_trading_max_wallet_risk_score: float = 40.0
    copy_trading_mirror_sells: bool = True
    copy_trading_require_anti_rug_screen: bool = True
    enable_rpc_pool: bool = True
    rpc_endpoints: tuple[str, ...] = ()
    rpc_pool_health_check_interval_seconds: float = 30.0
    rpc_pool_circuit_breaker_threshold: int = 3
    rpc_pool_circuit_breaker_cooldown_seconds: float = 60.0
    rpc_pool_broadcast_concurrency: int = 3

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
            "emergency_hard_lock_hours": self.emergency_hard_lock_hours,
            "auto_liquidate_on_circuit_breaker": self.auto_liquidate_on_circuit_breaker,
            "enable_trailing_stop": self.enable_trailing_stop,
            "trailing_stop_activation_pct": self.trailing_stop_activation_pct,
            "trailing_stop_drop_pct": self.trailing_stop_drop_pct,
            "enable_stagnant_exit": self.enable_stagnant_exit,
            "stagnant_timeout_seconds": self.stagnant_timeout_seconds,
            "enable_max_hold_timeout": self.enable_max_hold_timeout,
            "max_hold_time_seconds": self.max_hold_time_seconds,
            "stagnant_price_delta_threshold_pct": self.stagnant_price_delta_threshold_pct,
            "enable_tiered_take_profit": self.enable_tiered_take_profit,
            "tier_1_take_profit": self.tier_1_take_profit,
            "tier_1_sell_fraction": self.tier_1_sell_fraction,
            "tier_2_take_profit": self.tier_2_take_profit,
            "tier_2_sell_fraction": self.tier_2_sell_fraction,
            "moonbag_trailing_floor": self.moonbag_trailing_floor,
            "enable_anti_rug_filters": self.enable_anti_rug_filters,
            "max_dev_24h_launches": self.max_dev_24h_launches,
            "max_creator_initial_holding_pct": self.max_creator_initial_holding_pct,
            "max_top5_holder_concentration_pct": self.max_top5_holder_concentration_pct,
            "max_gini_coefficient": self.max_gini_coefficient,
            "require_social_links": self.require_social_links,
            "min_social_links_count": self.min_social_links_count,
            "max_acceptable_risk_score": self.max_acceptable_risk_score,
            "screening_cache_ttl_seconds": self.screening_cache_ttl_seconds,
            "enable_momentum_signals": self.enable_momentum_signals,
            "momentum_window_seconds": self.momentum_window_seconds,
            "momentum_min_buy_ratio": self.momentum_min_buy_ratio,
            "momentum_min_z_score": self.momentum_min_z_score,
            "momentum_min_unique_buyers": self.momentum_min_unique_buyers,
            "momentum_min_net_inflow_sol": self.momentum_min_net_inflow_sol,
            "momentum_baseline_window_seconds": self.momentum_baseline_window_seconds,
            "momentum_max_token_age_seconds": self.momentum_max_token_age_seconds,
            "enable_raydium_migration_sniping": self.enable_raydium_migration_sniping,
            "raydium_pre_migration_sol_threshold": self.raydium_pre_migration_sol_threshold,
            "raydium_buy_amount_sol": self.raydium_buy_amount_sol,
            "raydium_slippage_bps": self.raydium_slippage_bps,
            "raydium_priority_fee_lamports": self.raydium_priority_fee_lamports,
            "raydium_max_entry_latency_seconds": self.raydium_max_entry_latency_seconds,
            "enable_copy_trading": self.enable_copy_trading,
            "copy_trading_wallets": list(self.copy_trading_wallets),
            "copy_trading_sizing_mode": self.copy_trading_sizing_mode,
            "copy_trading_scale_factor": self.copy_trading_scale_factor,
            "copy_trading_min_wallet_win_rate": self.copy_trading_min_wallet_win_rate,
            "copy_trading_max_wallet_risk_score": self.copy_trading_max_wallet_risk_score,
            "copy_trading_mirror_sells": self.copy_trading_mirror_sells,
            "copy_trading_require_anti_rug_screen": self.copy_trading_require_anti_rug_screen,
            "enable_rpc_pool": self.enable_rpc_pool,
            "rpc_endpoints": list(self.rpc_endpoints),
            "rpc_pool_health_check_interval_seconds": self.rpc_pool_health_check_interval_seconds,
            "rpc_pool_circuit_breaker_threshold": self.rpc_pool_circuit_breaker_threshold,
            "rpc_pool_circuit_breaker_cooldown_seconds": self.rpc_pool_circuit_breaker_cooldown_seconds,
            "rpc_pool_broadcast_concurrency": self.rpc_pool_broadcast_concurrency,
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
