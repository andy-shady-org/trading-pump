from __future__ import annotations

from typing import Any

from pumpfun_trading.strategies.base import TradingBotConfig

DEFAULT_PRESETS: dict[str, dict[str, Any]] = {
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
        "emergency_hard_lock_hours": 24.0,
        "auto_liquidate_on_circuit_breaker": True,
        "enable_trailing_stop": True,
        "trailing_stop_activation_pct": 0.35,
        "trailing_stop_drop_pct": 0.10,
        "enable_stagnant_exit": True,
        "stagnant_timeout_seconds": 180.0,
        "enable_max_hold_timeout": True,
        "max_hold_time_seconds": 900.0,
        "stagnant_price_delta_threshold_pct": 0.005,
        "enable_tiered_take_profit": True,
        "tier_1_take_profit": 1.8,
        "tier_1_sell_fraction": 0.60,
        "tier_2_take_profit": 2.8,
        "tier_2_sell_fraction": 0.20,
        "moonbag_trailing_floor": 2.0,
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 2,
        "max_creator_initial_holding_pct": 0.05,
        "max_top5_holder_concentration_pct": 0.10,
        "max_gini_coefficient": 0.80,
        "require_social_links": True,
        "min_social_links_count": 2,
        "max_acceptable_risk_score": 30.0,
        "screening_cache_ttl_seconds": 60,
        "enable_momentum_signals": True,
        "momentum_window_seconds": 30,
        "momentum_min_buy_ratio": 4.0,
        "momentum_min_z_score": 3.0,
        "momentum_min_unique_buyers": 5,
        "momentum_min_net_inflow_sol": 1.0,
        "momentum_baseline_window_seconds": 300,
        "momentum_max_token_age_seconds": 900,
        "enable_raydium_migration_sniping": True,
        "raydium_pre_migration_sol_threshold": 82.0,
        "raydium_buy_amount_sol": 0.01,
        "raydium_slippage_bps": 300,
        "raydium_priority_fee_lamports": 50_000,
        "raydium_max_entry_latency_seconds": 15.0,
        "enable_copy_trading": True,
        "copy_trading_wallets": (),
        "copy_trading_sizing_mode": "proportional",
        "copy_trading_scale_factor": 0.8,
        "copy_trading_min_wallet_win_rate": 0.70,
        "copy_trading_max_wallet_risk_score": 30.0,
        "copy_trading_mirror_sells": True,
        "copy_trading_require_anti_rug_screen": True,
        "enable_rpc_pool": True,
        "rpc_endpoints": (),
        "rpc_pool_health_check_interval_seconds": 30.0,
        "rpc_pool_circuit_breaker_threshold": 2,
        "rpc_pool_circuit_breaker_cooldown_seconds": 90.0,
        "rpc_pool_broadcast_concurrency": 2,
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
        "emergency_hard_lock_hours": 24.0,
        "auto_liquidate_on_circuit_breaker": True,
        "enable_trailing_stop": True,
        "trailing_stop_activation_pct": 0.50,
        "trailing_stop_drop_pct": 0.15,
        "enable_stagnant_exit": True,
        "stagnant_timeout_seconds": 120.0,
        "enable_max_hold_timeout": True,
        "max_hold_time_seconds": 600.0,
        "stagnant_price_delta_threshold_pct": 0.005,
        "enable_tiered_take_profit": True,
        "tier_1_take_profit": 2.0,
        "tier_1_sell_fraction": 0.50,
        "tier_2_take_profit": 3.5,
        "tier_2_sell_fraction": 0.25,
        "moonbag_trailing_floor": 2.5,
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 5,
        "max_creator_initial_holding_pct": 0.10,
        "max_top5_holder_concentration_pct": 0.15,
        "max_gini_coefficient": 0.85,
        "require_social_links": False,
        "min_social_links_count": 0,
        "max_acceptable_risk_score": 50.0,
        "screening_cache_ttl_seconds": 60,
        "enable_momentum_signals": True,
        "momentum_window_seconds": 30,
        "momentum_min_buy_ratio": 3.0,
        "momentum_min_z_score": 2.5,
        "momentum_min_unique_buyers": 3,
        "momentum_min_net_inflow_sol": 0.5,
        "momentum_baseline_window_seconds": 300,
        "momentum_max_token_age_seconds": 1800,
        "enable_raydium_migration_sniping": True,
        "raydium_pre_migration_sol_threshold": 80.0,
        "raydium_buy_amount_sol": 0.02,
        "raydium_slippage_bps": 500,
        "raydium_priority_fee_lamports": 100_000,
        "raydium_max_entry_latency_seconds": 30.0,
        "enable_copy_trading": True,
        "copy_trading_wallets": (),
        "copy_trading_sizing_mode": "proportional",
        "copy_trading_scale_factor": 1.0,
        "copy_trading_min_wallet_win_rate": 0.60,
        "copy_trading_max_wallet_risk_score": 40.0,
        "copy_trading_mirror_sells": True,
        "copy_trading_require_anti_rug_screen": True,
        "enable_rpc_pool": True,
        "rpc_endpoints": (),
        "rpc_pool_health_check_interval_seconds": 30.0,
        "rpc_pool_circuit_breaker_threshold": 3,
        "rpc_pool_circuit_breaker_cooldown_seconds": 60.0,
        "rpc_pool_broadcast_concurrency": 3,
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
        "emergency_hard_lock_hours": 12.0,
        "auto_liquidate_on_circuit_breaker": True,
        "enable_trailing_stop": True,
        "trailing_stop_activation_pct": 0.75,
        "trailing_stop_drop_pct": 0.20,
        "enable_stagnant_exit": True,
        "stagnant_timeout_seconds": 60.0,
        "enable_max_hold_timeout": True,
        "max_hold_time_seconds": 300.0,
        "stagnant_price_delta_threshold_pct": 0.005,
        "enable_tiered_take_profit": True,
        "tier_1_take_profit": 2.5,
        "tier_1_sell_fraction": 0.40,
        "tier_2_take_profit": 4.5,
        "tier_2_sell_fraction": 0.30,
        "moonbag_trailing_floor": 3.0,
        "enable_anti_rug_filters": True,
        "max_dev_24h_launches": 8,
        "max_creator_initial_holding_pct": 0.15,
        "max_top5_holder_concentration_pct": 0.25,
        "max_gini_coefficient": 0.90,
        "require_social_links": False,
        "min_social_links_count": 0,
        "max_acceptable_risk_score": 70.0,
        "screening_cache_ttl_seconds": 60,
        "enable_momentum_signals": True,
        "momentum_window_seconds": 30,
        "momentum_min_buy_ratio": 2.0,
        "momentum_min_z_score": 2.0,
        "momentum_min_unique_buyers": 2,
        "momentum_min_net_inflow_sol": 0.25,
        "momentum_baseline_window_seconds": 300,
        "momentum_max_token_age_seconds": 3600,
        "enable_raydium_migration_sniping": True,
        "raydium_pre_migration_sol_threshold": 75.0,
        "raydium_buy_amount_sol": 0.05,
        "raydium_slippage_bps": 800,
        "raydium_priority_fee_lamports": 200_000,
        "raydium_max_entry_latency_seconds": 60.0,
        "enable_copy_trading": True,
        "copy_trading_wallets": (),
        "copy_trading_sizing_mode": "proportional",
        "copy_trading_scale_factor": 1.5,
        "copy_trading_min_wallet_win_rate": 0.50,
        "copy_trading_max_wallet_risk_score": 50.0,
        "copy_trading_mirror_sells": True,
        "copy_trading_require_anti_rug_screen": True,
        "enable_rpc_pool": True,
        "rpc_endpoints": (),
        "rpc_pool_health_check_interval_seconds": 20.0,
        "rpc_pool_circuit_breaker_threshold": 4,
        "rpc_pool_circuit_breaker_cooldown_seconds": 45.0,
        "rpc_pool_broadcast_concurrency": 4,
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
        emergency_hard_lock_hours=float(base.get("emergency_hard_lock_hours", 24.0)),
        auto_liquidate_on_circuit_breaker=bool(
            base.get("auto_liquidate_on_circuit_breaker", True)
        ),
        enable_trailing_stop=bool(base.get("enable_trailing_stop", True)),
        trailing_stop_activation_pct=float(
            base.get("trailing_stop_activation_pct", 0.50)
        ),
        trailing_stop_drop_pct=float(base.get("trailing_stop_drop_pct", 0.15)),
        enable_stagnant_exit=bool(base.get("enable_stagnant_exit", True)),
        stagnant_timeout_seconds=float(base.get("stagnant_timeout_seconds", 120.0)),
        enable_max_hold_timeout=bool(base.get("enable_max_hold_timeout", True)),
        max_hold_time_seconds=float(base.get("max_hold_time_seconds", 600.0)),
        stagnant_price_delta_threshold_pct=float(
            base.get("stagnant_price_delta_threshold_pct", 0.005)
        ),
        enable_tiered_take_profit=bool(base.get("enable_tiered_take_profit", True)),
        tier_1_take_profit=float(base.get("tier_1_take_profit", 2.0)),
        tier_1_sell_fraction=float(base.get("tier_1_sell_fraction", 0.50)),
        tier_2_take_profit=float(base.get("tier_2_take_profit", 3.5)),
        tier_2_sell_fraction=float(base.get("tier_2_sell_fraction", 0.25)),
        moonbag_trailing_floor=float(base.get("moonbag_trailing_floor", 2.5)),
        enable_anti_rug_filters=bool(base.get("enable_anti_rug_filters", True)),
        max_dev_24h_launches=int(base.get("max_dev_24h_launches", 5)),
        max_creator_initial_holding_pct=float(
            base.get("max_creator_initial_holding_pct", 0.10)
        ),
        max_top5_holder_concentration_pct=float(
            base.get("max_top5_holder_concentration_pct", 0.15)
        ),
        max_gini_coefficient=float(base.get("max_gini_coefficient", 0.85)),
        require_social_links=bool(base.get("require_social_links", False)),
        min_social_links_count=int(base.get("min_social_links_count", 0)),
        max_acceptable_risk_score=float(base.get("max_acceptable_risk_score", 50.0)),
        screening_cache_ttl_seconds=int(base.get("screening_cache_ttl_seconds", 60)),
        enable_momentum_signals=bool(base.get("enable_momentum_signals", True)),
        momentum_window_seconds=int(base.get("momentum_window_seconds", 30)),
        momentum_min_buy_ratio=float(base.get("momentum_min_buy_ratio", 3.0)),
        momentum_min_z_score=float(base.get("momentum_min_z_score", 2.5)),
        momentum_min_unique_buyers=int(base.get("momentum_min_unique_buyers", 3)),
        momentum_min_net_inflow_sol=float(base.get("momentum_min_net_inflow_sol", 0.5)),
        momentum_baseline_window_seconds=int(
            base.get("momentum_baseline_window_seconds", 300)
        ),
        momentum_max_token_age_seconds=int(
            base.get("momentum_max_token_age_seconds", 1800)
        ),
        enable_raydium_migration_sniping=bool(
            base.get("enable_raydium_migration_sniping", True)
        ),
        raydium_pre_migration_sol_threshold=float(
            base.get("raydium_pre_migration_sol_threshold", 80.0)
        ),
        raydium_buy_amount_sol=float(base.get("raydium_buy_amount_sol", 0.02)),
        raydium_slippage_bps=int(base.get("raydium_slippage_bps", 500)),
        raydium_priority_fee_lamports=int(
            base.get("raydium_priority_fee_lamports", 100_000)
        ),
        raydium_max_entry_latency_seconds=float(
            base.get("raydium_max_entry_latency_seconds", 30.0)
        ),
        enable_copy_trading=bool(base.get("enable_copy_trading", True)),
        copy_trading_wallets=tuple(base.get("copy_trading_wallets") or ()),
        copy_trading_sizing_mode=str(
            base.get("copy_trading_sizing_mode", "proportional")
        ),
        copy_trading_scale_factor=float(base.get("copy_trading_scale_factor", 1.0)),
        copy_trading_min_wallet_win_rate=float(
            base.get("copy_trading_min_wallet_win_rate", 0.60)
        ),
        copy_trading_max_wallet_risk_score=float(
            base.get("copy_trading_max_wallet_risk_score", 40.0)
        ),
        copy_trading_mirror_sells=bool(base.get("copy_trading_mirror_sells", True)),
        copy_trading_require_anti_rug_screen=bool(
            base.get("copy_trading_require_anti_rug_screen", True)
        ),
        enable_rpc_pool=bool(base.get("enable_rpc_pool", True)),
        rpc_endpoints=tuple(base.get("rpc_endpoints") or ()),
        rpc_pool_health_check_interval_seconds=float(
            base.get("rpc_pool_health_check_interval_seconds", 30.0)
        ),
        rpc_pool_circuit_breaker_threshold=int(
            base.get("rpc_pool_circuit_breaker_threshold", 3)
        ),
        rpc_pool_circuit_breaker_cooldown_seconds=float(
            base.get("rpc_pool_circuit_breaker_cooldown_seconds", 60.0)
        ),
        rpc_pool_broadcast_concurrency=int(
            base.get("rpc_pool_broadcast_concurrency", 3)
        ),
    )
    if config.buy_amount_sol <= 0:
        raise ValueError("buy_amount_sol must be greater than zero.")
    if not 0 < config.stop_loss < config.take_profit:
        raise ValueError(
            "stop_loss must be less than take_profit and both must be greater than zero."
        )
    if config.max_active_positions < 1:
        raise ValueError("max_active_positions must be at least 1.")
    if config.stagnant_timeout_seconds <= 0:
        raise ValueError("stagnant_timeout_seconds must be greater than zero.")
    if config.max_hold_time_seconds <= 0:
        raise ValueError("max_hold_time_seconds must be greater than zero.")
    return config
