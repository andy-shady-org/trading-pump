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
        "enable_raydium_migration_sniping": False,
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
        "drawdown_reference_mode": "adaptive_ratchet",
        "profit_ratchet_ratio": 0.60,
        "profit_drawdown_tolerance_pct": 0.25,
        "enable_diagnostic_events": True,
        "event_log_path": "events.jsonl",
        "event_log_subsystems": (
            "stream",
            "screening",
            "strategy",
            "execution",
            "risk",
            "lifecycle",
        ),
        "enable_dynamic_slippage": True,
        "min_slippage_bps": 100,
        "max_slippage_bps": 350,
        "max_exit_slippage_bps": 3000,
        "priority_fee_mode": "adaptive",
        "volatility_slippage_multiplier": 0.8,
        "price_impact_slippage_multiplier": 0.8,
        "enable_capital_rotation": True,
        "displacement_min_conviction_percentile": 0.98,
        "displacement_hurdle_rate_pct": 0.04,
        "min_hold_before_displacement_seconds": 60.0,
        "displacement_evaluation_interval_seconds": 2.0,
        "enable_pre_graduation_harvesting": True,
        "pre_graduation_entry_progress_pct": 0.75,
        "pre_graduation_max_entry_progress_pct": 0.85,
        "pre_graduation_min_acceleration": 0.0,
        "pre_graduation_tranches": (
            {"progress_pct": 0.90, "sell_fraction": 0.35},
            {"progress_pct": 0.95, "sell_fraction": 0.35},
        ),
        "enable_cluster_analysis": True,
        "max_cluster_concentration_pct": 0.15,
        "max_single_cluster_pct": 0.10,
        "max_sybil_wash_ratio": 0.10,
        "cluster_trace_depth": 3,
        "enable_cross_venue_arbitrage": True,
        "enable_mempool_backrunning": True,
        "min_arbitrage_profit_sol": 0.005,
        "min_arbitrage_spread_pct": 0.020,
        "max_arbitrage_input_sol": 0.25,
        "min_arbitrage_input_sol": 0.01,
        "arbitrage_jito_tip_profit_share_pct": 0.40,
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
        "enable_raydium_migration_sniping": False,
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
        "drawdown_reference_mode": "adaptive_ratchet",
        "profit_ratchet_ratio": 0.50,
        "profit_drawdown_tolerance_pct": 0.35,
        "enable_diagnostic_events": True,
        "event_log_path": "events.jsonl",
        "event_log_subsystems": (
            "stream",
            "screening",
            "strategy",
            "execution",
            "risk",
            "lifecycle",
        ),
        "enable_dynamic_slippage": True,
        "min_slippage_bps": 100,
        "max_slippage_bps": 500,
        "max_exit_slippage_bps": 5000,
        "priority_fee_mode": "adaptive",
        "volatility_slippage_multiplier": 1.0,
        "price_impact_slippage_multiplier": 1.0,
        "enable_capital_rotation": True,
        "displacement_min_conviction_percentile": 0.95,
        "displacement_hurdle_rate_pct": 0.03,
        "min_hold_before_displacement_seconds": 45.0,
        "displacement_evaluation_interval_seconds": 2.0,
        "enable_pre_graduation_harvesting": True,
        "pre_graduation_entry_progress_pct": 0.70,
        "pre_graduation_max_entry_progress_pct": 0.85,
        "pre_graduation_min_acceleration": 0.0,
        "pre_graduation_tranches": (
            {"progress_pct": 0.92, "sell_fraction": 0.30},
            {"progress_pct": 0.97, "sell_fraction": 0.30},
        ),
        "enable_cluster_analysis": True,
        "max_cluster_concentration_pct": 0.25,
        "max_single_cluster_pct": 0.20,
        "max_sybil_wash_ratio": 0.20,
        "cluster_trace_depth": 2,
        "enable_cross_venue_arbitrage": True,
        "enable_mempool_backrunning": True,
        "min_arbitrage_profit_sol": 0.003,
        "min_arbitrage_spread_pct": 0.015,
        "max_arbitrage_input_sol": 0.50,
        "min_arbitrage_input_sol": 0.01,
        "arbitrage_jito_tip_profit_share_pct": 0.50,
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
        "enable_raydium_migration_sniping": False,
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
        "drawdown_reference_mode": "adaptive_ratchet",
        "profit_ratchet_ratio": 0.40,
        "profit_drawdown_tolerance_pct": 0.45,
        "enable_diagnostic_events": True,
        "event_log_path": "events.jsonl",
        "event_log_subsystems": (
            "stream",
            "screening",
            "strategy",
            "execution",
            "risk",
            "lifecycle",
        ),
        "enable_dynamic_slippage": True,
        "min_slippage_bps": 150,
        "max_slippage_bps": 800,
        "max_exit_slippage_bps": 6000,
        "priority_fee_mode": "adaptive",
        "volatility_slippage_multiplier": 1.5,
        "price_impact_slippage_multiplier": 1.5,
        "enable_capital_rotation": True,
        "displacement_min_conviction_percentile": 0.90,
        "displacement_hurdle_rate_pct": 0.02,
        "min_hold_before_displacement_seconds": 30.0,
        "displacement_evaluation_interval_seconds": 1.0,
        "enable_pre_graduation_harvesting": True,
        "pre_graduation_entry_progress_pct": 0.65,
        "pre_graduation_max_entry_progress_pct": 0.90,
        "pre_graduation_min_acceleration": 0.0,
        "pre_graduation_tranches": (
            {"progress_pct": 0.90, "sell_fraction": 0.25},
            {"progress_pct": 0.95, "sell_fraction": 0.25},
        ),
        "enable_cluster_analysis": True,
        "max_cluster_concentration_pct": 0.35,
        "max_single_cluster_pct": 0.30,
        "max_sybil_wash_ratio": 0.30,
        "cluster_trace_depth": 2,
        "enable_cross_venue_arbitrage": True,
        "enable_mempool_backrunning": True,
        "min_arbitrage_profit_sol": 0.002,
        "min_arbitrage_spread_pct": 0.010,
        "max_arbitrage_input_sol": 1.00,
        "min_arbitrage_input_sol": 0.01,
        "arbitrage_jito_tip_profit_share_pct": 0.60,
    },
}

# Confirmed momentum (Phase 4c, FEAT-52): the conservative screen and limits,
# but no buy at the create event. Thresholds are starting points; the canary
# only uses values that were net positive in replay on an unseen capture
# (docs/dev/STRATEGY-PIVOT.md).
DEFAULT_PRESETS["momentum"] = {
    **DEFAULT_PRESETS["conservative"],
    "entry_mode": "confirmed",
    "buy_amount_sol": 0.02,
    "max_position_size_sol": 0.02,
    "max_active_positions": 2,
    "max_total_exposure_sol": 0.05,
    # One 0.02 SOL position is 40% of the 0.05 SOL cap; the conservative 25%
    # would refuse every buy.
    "max_token_concentration_pct": 0.5,
    "max_loss_per_trade_sol": 0.02,
    "min_market_cap_sol": 35.0,
    "momentum_max_market_cap_sol": 75.0,
    # Picked on the first half of the v0.2.3 capture, positive on the held-out
    # half (STRATEGY-PIVOT.md 6.1). The z-score is off: tokens this young have
    # no 300 s baseline.
    "momentum_min_token_age_seconds": 20.0,
    "momentum_max_token_age_seconds": 600,
    "momentum_window_seconds": 30,
    "momentum_min_buy_ratio": 1.5,
    "momentum_min_z_score": 0.0,
    "momentum_min_unique_buyers": 3,
    "momentum_min_net_inflow_sol": 0.5,
    "watch_ttl_seconds": 600.0,
    "watch_max_mints": 300,
    "watch_poll_interval_seconds": 2.0,
    "watch_promote_min_sol_growth": 3.0,
    "watch_max_trade_subscriptions": 20,
    "stagnant_timeout_seconds": 35.0,
    "stagnant_min_buy_sol": 0.1,
    "breakeven_ratchet_activation_pct": 0.25,
    "breakeven_buffer_pct": 0.05,
    "max_entry_cost_share_pct": 0.10,
    # Skip a buy whose curve ran > 8% above the signal before the fill (rc.1
    # 24 h capture, STRATEGY-PIVOT.md 6.4).
    "momentum_max_entry_drift_pct": 0.08,
    # Paper sells pay what replay charges a sell, so the two agree (BUG-126).
    "paper_exit_slippage_bps": 100,
    # 0.92 beat 0.85 in both halves of the v0.2.3, rc.1 and rc.2 captures
    # (STRATEGY-PIVOT.md 6.10).
    "stop_loss": 0.92,
    "take_profit": 3.0,
    "tier_1_take_profit": 1.5,
    "tier_1_sell_fraction": 0.50,
    "tier_2_take_profit": 2.0,
    "tier_2_sell_fraction": 0.30,
    "moonbag_trailing_floor": 1.4,
    "trailing_stop_activation_pct": 0.25,
    "trailing_stop_drop_pct": 0.12,
    "max_hold_time_seconds": 600.0,
    # Off until a 72 h paper pilot shows them positive (RELEASE-GATE.md 3.5).
    "enable_pre_graduation_harvesting": False,
    "enable_raydium_migration_sniping": False,
    "enable_copy_trading": False,
    "enable_cross_venue_arbitrage": False,
    "enable_mempool_backrunning": False,
    "enable_capital_rotation": False,
}


CONFIG_ALIASES: dict[str, str] = {
    # Stagnation exit timeouts
    "stagnant_curve_timeout_seconds": "stagnant_timeout_seconds",
    "stagnant_curve_timeout": "stagnant_timeout_seconds",
    "stagnation_timeout_seconds": "stagnant_timeout_seconds",
    "stagnation_timeout": "stagnant_timeout_seconds",
    # Take-profit tier multipliers and sell fractions
    "take_profit_tier1_multiplier": "tier_1_take_profit",
    "take_profit_tier_1_multiplier": "tier_1_take_profit",
    "take_profit_tier1": "tier_1_take_profit",
    "tier1_take_profit": "tier_1_take_profit",
    "take_profit_tier1_pct": "tier_1_sell_fraction",
    "take_profit_tier_1_pct": "tier_1_sell_fraction",
    "tier1_sell_fraction": "tier_1_sell_fraction",
    "take_profit_tier2_multiplier": "tier_2_take_profit",
    "take_profit_tier_2_multiplier": "tier_2_take_profit",
    "take_profit_tier2": "tier_2_take_profit",
    "tier2_take_profit": "tier_2_take_profit",
    "take_profit_tier2_pct": "tier_2_sell_fraction",
    "take_profit_tier_2_pct": "tier_2_sell_fraction",
    "tier2_sell_fraction": "tier_2_sell_fraction",
    # Stop loss
    "stop_loss_pct": "stop_loss",
    # Anti-rug and creator holding limits
    "max_creator_initial_pct": "max_creator_initial_holding_pct",
    "max_creator_initial_holding": "max_creator_initial_holding_pct",
    "max_top5_holder_pct": "max_top5_holder_concentration_pct",
    # Momentum and order flow filters
    "min_order_flow_buyers": "momentum_min_unique_buyers",
    "min_buyers": "momentum_min_unique_buyers",
    "order_flow_min_buyers": "momentum_min_unique_buyers",
    # Strategy booleans
    "dynamic_slippage_enabled": "enable_dynamic_slippage",
    "anti_rug_filters_enabled": "enable_anti_rug_filters",
    "capital_rotation_enabled": "enable_capital_rotation",
    "pre_graduation_harvesting_enabled": "enable_pre_graduation_harvesting",
    "cross_venue_arbitrage_enabled": "enable_cross_venue_arbitrage",
    "mempool_backrunning_enabled": "enable_mempool_backrunning",
    "cluster_analysis_enabled": "enable_cluster_analysis",
    "copy_trading_enabled": "enable_copy_trading",
    "momentum_signals_enabled": "enable_momentum_signals",
    "raydium_migration_sniping_enabled": "enable_raydium_migration_sniping",
    "tiered_take_profit_enabled": "enable_tiered_take_profit",
    "trailing_stop_enabled": "enable_trailing_stop",
    "stagnant_exit_enabled": "enable_stagnant_exit",
    "max_hold_timeout_enabled": "enable_max_hold_timeout",
}


def normalize_config_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize configuration dictionaries by mapping legacy and optimizer aliases to canonical fields."""
    normalized: dict[str, Any] = {}
    for k, v in data.items():
        canonical_key = CONFIG_ALIASES.get(k, k)
        normalized[canonical_key] = v
    return normalized


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
        normalized_overrides = normalize_config_dict(overrides)
        base.update({k: v for k, v in normalized_overrides.items() if v is not None})

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
        stream_heartbeat_seconds=float(base.get("stream_heartbeat_seconds", 20.0)),
        dry_run=bool(base.get("dry_run", False)),
        paper_trade=bool(base.get("paper_trade", False)),
        verbose=bool(base.get("verbose", True)),
        headless=bool(base.get("headless", False)),
        stream_url=str(base.get("stream_url", "wss://pumpportal.fun/api/data")),
        api_base_url=str(base.get("api_base_url", "https://frontend-api-v3.pump.fun")),
        strategy_preset=preset_key,
        max_total_exposure_sol=float(base["max_total_exposure_sol"]),
        max_position_size_sol=float(base["max_position_size_sol"]),
        max_token_concentration_pct=float(base["max_token_concentration_pct"]),
        max_loss_per_trade_sol=float(base["max_loss_per_trade_sol"]),
        max_daily_drawdown_pct=float(base["max_daily_drawdown_pct"]),
        max_cumulative_drawdown_pct=float(
            base.get("max_cumulative_drawdown_pct", 0.30)
        ),
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
        require_holder_data=bool(base.get("require_holder_data", False)),
        min_holder_count=max(0, int(base.get("min_holder_count", 0) or 0)),
        min_social_links_count=int(base.get("min_social_links_count", 0)),
        max_acceptable_risk_score=float(base.get("max_acceptable_risk_score", 50.0)),
        require_pump_mint_suffix=bool(base.get("require_pump_mint_suffix", True)),
        allow_mint_reentry=bool(base.get("allow_mint_reentry", False)),
        paper_entry_delay_seconds=max(
            0.0, float(base.get("paper_entry_delay_seconds", 0.0))
        ),
        entry_curve_wait_seconds=float(base.get("entry_curve_wait_seconds", 3.0)),
        paper_entry_slippage_bps=max(
            0, min(5_000, int(base.get("paper_entry_slippage_bps", 0)))
        ),
        paper_exit_slippage_bps=max(
            0, min(5_000, int(base.get("paper_exit_slippage_bps", 0)))
        ),
        paper_starting_balance_sol=max(
            0.0, float(base.get("paper_starting_balance_sol", 0.0))
        ),
        position_refresh_seconds=max(
            0.0, float(base.get("position_refresh_seconds", 1.0))
        ),
        require_trade_feed=bool(base.get("require_trade_feed", True)),
        trade_feed_probe_seconds=max(
            30.0, float(base.get("trade_feed_probe_seconds", 300.0))
        ),
        skip_mayhem_mode=bool(base.get("skip_mayhem_mode", True)),
        launch_skip_creator_buy_below_sol=float(
            base.get("launch_skip_creator_buy_below_sol", 0.0)
        ),
        screening_cache_ttl_seconds=int(base.get("screening_cache_ttl_seconds", 60)),
        entry_mode=str(base.get("entry_mode", "launch")).strip().lower(),
        watch_ttl_seconds=float(base.get("watch_ttl_seconds", 600.0)),
        watch_max_mints=int(base.get("watch_max_mints", 300)),
        watch_poll_interval_seconds=float(base.get("watch_poll_interval_seconds", 2.0)),
        watch_promote_min_sol_growth=float(
            base.get("watch_promote_min_sol_growth", 1.5)
        ),
        watch_max_trade_subscriptions=int(
            base.get("watch_max_trade_subscriptions", 20)
        ),
        near_graduation_max_mints=int(base.get("near_graduation_max_mints", 0) or 0),
        near_graduation_min_progress_pct=float(
            base.get("near_graduation_min_progress_pct", 0.50)
        ),
        near_graduation_stall_seconds=float(
            base.get("near_graduation_stall_seconds", 300.0)
        ),
        near_graduation_ttl_seconds=float(
            base.get("near_graduation_ttl_seconds", 3600.0)
        ),
        near_graduation_poll_interval_seconds=float(
            base.get("near_graduation_poll_interval_seconds", 6.0)
        ),
        capture_curve_polls=bool(base.get("capture_curve_polls", True)),
        screen_reject_sample_pct=float(base.get("screen_reject_sample_pct", 0.0)),
        screen_reject_sample_max_mints=int(
            base.get("screen_reject_sample_max_mints", 100)
        ),
        screen_reject_sample_ttl_seconds=float(
            base.get("screen_reject_sample_ttl_seconds", 1800.0)
        ),
        graduation_discovery_scan_seconds=float(
            base.get("graduation_discovery_scan_seconds", 0.0)
        ),
        graduation_discovery_min_real_sol=float(
            base.get("graduation_discovery_min_real_sol", 40.0)
        ),
        graduation_discovery_max_mints=int(
            base.get("graduation_discovery_max_mints", 100)
        ),
        graduation_discovery_ttl_seconds=float(
            base.get("graduation_discovery_ttl_seconds", 7200.0)
        ),
        launch_sample_pct=float(base.get("launch_sample_pct", 0.0)),
        launch_sample_max_mints=int(base.get("launch_sample_max_mints", 300)),
        launch_sample_ttl_seconds=float(base.get("launch_sample_ttl_seconds", 900.0)),
        launch_sample_poll_interval_seconds=float(
            base.get("launch_sample_poll_interval_seconds", 5.0)
        ),
        launch_sample_extend_seconds=float(
            base.get("launch_sample_extend_seconds", 0.0)
        ),
        launch_sample_extend_min_real_sol=float(
            base.get("launch_sample_extend_min_real_sol", 1.0)
        ),
        launch_sample_extend_poll_interval_seconds=float(
            base.get("launch_sample_extend_poll_interval_seconds", 15.0)
        ),
        post_exit_observation_seconds=float(
            base.get("post_exit_observation_seconds", 0.0)
        ),
        post_exit_max_mints=int(base.get("post_exit_max_mints", 100)),
        post_exit_poll_interval_seconds=float(
            base.get("post_exit_poll_interval_seconds", 2.0)
        ),
        graduation_observation_seconds=float(
            base.get("graduation_observation_seconds", 0.0)
        ),
        graduation_observation_max_mints=int(
            base.get("graduation_observation_max_mints", 300)
        ),
        graduation_observation_poll_interval_seconds=float(
            base.get("graduation_observation_poll_interval_seconds", 5.0)
        ),
        graduation_observation_fast_seconds=float(
            base.get("graduation_observation_fast_seconds", 300.0)
        ),
        graduation_observation_fast_poll_interval_seconds=float(
            base.get("graduation_observation_fast_poll_interval_seconds", 2.0)
        ),
        observation_poll_interval_seconds=float(
            base.get("observation_poll_interval_seconds", 5.0)
        ),
        record_stop_crossings=bool(base.get("record_stop_crossings", False)),
        shadow_variants=tuple(base.get("shadow_variants") or ()),
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
        momentum_min_token_age_seconds=max(
            0.0, float(base.get("momentum_min_token_age_seconds", 60.0))
        ),
        momentum_max_market_cap_sol=float(
            base.get("momentum_max_market_cap_sol", 75.0)
        ),
        stagnant_min_buy_sol=max(0.0, float(base.get("stagnant_min_buy_sol", 0.1))),
        breakeven_ratchet_activation_pct=max(
            0.0, float(base.get("breakeven_ratchet_activation_pct", 0.25))
        ),
        breakeven_buffer_pct=float(base.get("breakeven_buffer_pct", 0.05)),
        max_entry_cost_share_pct=max(
            0.0, float(base.get("max_entry_cost_share_pct", 0.10))
        ),
        momentum_max_entry_drift_pct=max(
            0.0, float(base.get("momentum_max_entry_drift_pct", 0.0))
        ),
        stop_loss_arm_seconds=max(0.0, float(base.get("stop_loss_arm_seconds", 0.0))),
        stop_loss_demand_hold_seconds=max(
            0.0, float(base.get("stop_loss_demand_hold_seconds", 0.0))
        ),
        stop_loss_hard_floor=max(0.0, float(base.get("stop_loss_hard_floor", 0.0))),
        enable_pumpswap_exit=bool(base.get("enable_pumpswap_exit", True)),
        graduation_backfill_seconds=max(
            0.0, float(base.get("graduation_backfill_seconds", 30.0))
        ),
        enable_raydium_migration_sniping=bool(
            base.get("enable_raydium_migration_sniping", False)
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
        drawdown_reference_mode=str(
            base.get("drawdown_reference_mode", "adaptive_ratchet")
        ),
        profit_ratchet_ratio=float(base.get("profit_ratchet_ratio", 0.50)),
        profit_ratchet_min_gain_pct=float(
            base.get("profit_ratchet_min_gain_pct", 0.02)
        ),
        profit_drawdown_tolerance_pct=float(
            base.get("profit_drawdown_tolerance_pct", 0.35)
        ),
        enable_diagnostic_events=bool(base.get("enable_diagnostic_events", True)),
        event_log_path=str(base.get("event_log_path", "events.jsonl")),
        event_log_subsystems=tuple(
            base.get("event_log_subsystems")
            or (
                "stream",
                "screening",
                "strategy",
                "execution",
                "risk",
                "lifecycle",
            )
        ),
        log_file=base.get("log_file", "bot.log"),
        log_max_bytes=int(base.get("log_max_bytes", 10 * 1024 * 1024)),
        log_backup_count=int(base.get("log_backup_count", 5)),
        log_rotation_type=str(base.get("log_rotation_type", "size")),
        log_compress=bool(base.get("log_compress", True)),
        audit_max_bytes=int(base.get("audit_max_bytes", 10 * 1024 * 1024)),
        audit_backup_count=int(base.get("audit_backup_count", 10)),
        audit_retention_days=int(base.get("audit_retention_days", 30)),
        audit_compress=bool(base.get("audit_compress", True)),
        replay_max_bytes=int(base.get("replay_max_bytes", 50 * 1024 * 1024)),
        replay_backup_count=int(base.get("replay_backup_count", 10)),
        replay_retention_days=int(base.get("replay_retention_days", 30)),
        replay_compress=bool(base.get("replay_compress", True)),
        retention_check_interval_seconds=float(
            base.get("retention_check_interval_seconds", 3600.0)
        ),
        enable_dynamic_slippage=bool(base.get("enable_dynamic_slippage", True)),
        min_slippage_bps=int(base.get("min_slippage_bps", 100)),
        max_slippage_bps=int(base.get("max_slippage_bps", 500)),
        max_exit_slippage_bps=int(base.get("max_exit_slippage_bps", 5000)),
        close_token_account_on_full_exit=bool(
            base.get("close_token_account_on_full_exit", True)
        ),
        priority_fee_mode=str(base.get("priority_fee_mode", "adaptive")),
        volatility_slippage_multiplier=float(
            base.get("volatility_slippage_multiplier", 1.0)
        ),
        price_impact_slippage_multiplier=float(
            base.get("price_impact_slippage_multiplier", 1.0)
        ),
        enable_capital_rotation=bool(base.get("enable_capital_rotation", True)),
        displacement_min_conviction_percentile=float(
            base.get("displacement_min_conviction_percentile", 0.95)
        ),
        displacement_hurdle_rate_pct=float(
            base.get("displacement_hurdle_rate_pct", 0.03)
        ),
        min_hold_before_displacement_seconds=float(
            base.get("min_hold_before_displacement_seconds", 45.0)
        ),
        displacement_evaluation_interval_seconds=float(
            base.get("displacement_evaluation_interval_seconds", 2.0)
        ),
        enable_pre_graduation_harvesting=bool(
            base.get("enable_pre_graduation_harvesting", True)
        ),
        pre_graduation_entry_progress_pct=float(
            base.get("pre_graduation_entry_progress_pct", 0.70)
        ),
        pre_graduation_max_entry_progress_pct=float(
            base.get("pre_graduation_max_entry_progress_pct", 0.85)
        ),
        pre_graduation_min_acceleration=float(
            base.get("pre_graduation_min_acceleration", 0.0)
        ),
        pre_graduation_tranches=tuple(
            base.get("pre_graduation_tranches")
            or (
                {"progress_pct": 0.92, "sell_fraction": 0.30},
                {"progress_pct": 0.97, "sell_fraction": 0.30},
            )
        ),
        enable_cluster_analysis=bool(base.get("enable_cluster_analysis", True)),
        max_cluster_concentration_pct=float(
            base.get("max_cluster_concentration_pct", 0.25)
        ),
        max_single_cluster_pct=float(base.get("max_single_cluster_pct", 0.20)),
        max_sybil_wash_ratio=float(base.get("max_sybil_wash_ratio", 0.20)),
        cluster_trace_depth=int(base.get("cluster_trace_depth", 2)),
        enable_cross_venue_arbitrage=bool(
            base.get("enable_cross_venue_arbitrage", True)
        ),
        enable_mempool_backrunning=bool(base.get("enable_mempool_backrunning", True)),
        min_arbitrage_profit_sol=float(base.get("min_arbitrage_profit_sol", 0.003)),
        min_arbitrage_spread_pct=float(base.get("min_arbitrage_spread_pct", 0.015)),
        max_arbitrage_input_sol=float(base.get("max_arbitrage_input_sol", 0.50)),
        min_arbitrage_input_sol=float(base.get("min_arbitrage_input_sol", 0.01)),
        arbitrage_jito_tip_profit_share_pct=float(
            base.get("arbitrage_jito_tip_profit_share_pct", 0.50)
        ),
        # Every field must be passed here, or a config file value is dropped
        # without a word (BUG-125); test_presets checks the full field list.
        replay_log_path=(
            str(base["replay_log_path"]) if base.get("replay_log_path") else None
        ),
        daily_summary_alert=bool(base.get("daily_summary_alert", True)),
        daily_summary_hour_utc=int(base.get("daily_summary_hour_utc", 0)),
        degradation_alert_minutes=float(base.get("degradation_alert_minutes", 5.0)),
        profit_sweep_enabled=bool(base.get("profit_sweep_enabled", False)),
        profit_sweep_destination=str(base.get("profit_sweep_destination", "") or ""),
        profit_sweep_hot_floor_sol=float(base.get("profit_sweep_hot_floor_sol", 0.0)),
        profit_sweep_min_sol=float(base.get("profit_sweep_min_sol", 0.05)),
        profit_sweep_interval_seconds=float(
            base.get("profit_sweep_interval_seconds", 3600.0)
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
    if not 0.0 <= config.entry_curve_wait_seconds <= 10.0:
        raise ValueError("entry_curve_wait_seconds must be between 0 and 10.")
    if not 0.0 <= config.launch_skip_creator_buy_below_sol <= 10.0:
        raise ValueError("launch_skip_creator_buy_below_sol must be between 0 and 10.")
    if config.stream_heartbeat_seconds < 0:
        raise ValueError("stream_heartbeat_seconds must be zero (off) or positive.")
    if config.stop_loss_hard_floor and config.stop_loss_hard_floor >= config.stop_loss:
        raise ValueError("stop_loss_hard_floor must be below stop_loss (0 = none).")
    if config.stagnant_timeout_seconds <= 0:
        raise ValueError("stagnant_timeout_seconds must be greater than zero.")
    if config.max_hold_time_seconds <= 0:
        raise ValueError("max_hold_time_seconds must be greater than zero.")
    if config.drawdown_reference_mode not in {
        "adaptive_ratchet",
        "baseline",
        "trailing_hwm",
    }:
        raise ValueError(
            f"Invalid drawdown_reference_mode '{config.drawdown_reference_mode}'. "
            "Must be one of: 'adaptive_ratchet', 'baseline', 'trailing_hwm'."
        )
    if not 0.0 <= config.profit_ratchet_ratio <= 1.0:
        raise ValueError("profit_ratchet_ratio must be between 0.0 and 1.0.")
    if not 0.0 <= config.profit_ratchet_min_gain_pct <= 1.0:
        raise ValueError("profit_ratchet_min_gain_pct must be between 0.0 and 1.0.")
    if not 0.0 <= config.max_cumulative_drawdown_pct < 1.0:
        raise ValueError(
            "max_cumulative_drawdown_pct must be between 0.0 (off) and 1.0."
        )
    if not 0.0 < config.profit_drawdown_tolerance_pct <= 1.0:
        raise ValueError("profit_drawdown_tolerance_pct must be between 0.0 and 1.0.")
    if config.log_rotation_type not in {"size", "time", "none"}:
        raise ValueError(
            f"Invalid log_rotation_type '{config.log_rotation_type}'. "
            "Must be one of: 'size', 'time', 'none'."
        )
    if config.min_slippage_bps < 0 or config.max_slippage_bps < config.min_slippage_bps:
        raise ValueError(
            "Invalid slippage bounds: min_slippage_bps must be <= max_slippage_bps and >= 0."
        )
    if not 0.0 <= config.max_cluster_concentration_pct <= 1.0:
        raise ValueError("max_cluster_concentration_pct must be between 0.0 and 1.0.")
    if not 0.0 <= config.max_single_cluster_pct <= 1.0:
        raise ValueError("max_single_cluster_pct must be between 0.0 and 1.0.")
    if not 0.0 <= config.max_sybil_wash_ratio <= 1.0:
        raise ValueError("max_sybil_wash_ratio must be between 0.0 and 1.0.")
    if config.cluster_trace_depth < 1:
        raise ValueError("cluster_trace_depth must be at least 1.")
    _validate_entry_pipeline(config)
    return config


ENTRY_MODES = frozenset({"launch", "confirmed"})


def _validate_entry_pipeline(config: TradingBotConfig) -> None:
    """Fail fast on watch-list settings that would stall or unbound it (FEAT-51)."""
    if config.entry_mode not in ENTRY_MODES:
        raise ValueError(
            f"Invalid entry_mode '{config.entry_mode}'. "
            "Must be one of: 'launch', 'confirmed'."
        )
    if config.watch_ttl_seconds <= 0:
        raise ValueError("watch_ttl_seconds must be greater than zero.")
    if config.watch_max_mints < 1:
        raise ValueError("watch_max_mints must be at least 1.")
    if config.watch_poll_interval_seconds < 0.1:
        raise ValueError("watch_poll_interval_seconds must be at least 0.1.")
    if config.watch_promote_min_sol_growth < 0:
        raise ValueError("watch_promote_min_sol_growth must not be negative.")
    if config.watch_max_trade_subscriptions < 0:
        raise ValueError("watch_max_trade_subscriptions must not be negative.")
    if config.near_graduation_max_mints < 0:
        raise ValueError("near_graduation_max_mints must not be negative.")
    if not 0.0 < config.near_graduation_min_progress_pct < 1.0:
        raise ValueError("near_graduation_min_progress_pct must be between 0 and 1.")
    if config.near_graduation_stall_seconds <= 0:
        raise ValueError("near_graduation_stall_seconds must be greater than zero.")
    if config.near_graduation_ttl_seconds < config.watch_ttl_seconds:
        raise ValueError("near_graduation_ttl_seconds must be >= watch_ttl_seconds.")
    if config.near_graduation_poll_interval_seconds < 0.1:
        raise ValueError("near_graduation_poll_interval_seconds must be at least 0.1.")
    _validate_observations(config)
    from pumpfun_trading.strategies.shadow import parse_shadow_variants

    parse_shadow_variants(config.shadow_variants)
    if config.entry_mode != "confirmed":
        return
    # The momentum band only applies to confirmed entries (FEAT-52).
    if config.momentum_max_market_cap_sol <= config.min_market_cap_sol:
        raise ValueError(
            "momentum_max_market_cap_sol must be greater than min_market_cap_sol."
        )
    if config.momentum_min_token_age_seconds >= config.momentum_max_token_age_seconds:
        raise ValueError(
            "momentum_min_token_age_seconds must be below "
            "momentum_max_token_age_seconds."
        )
    if (
        config.breakeven_ratchet_activation_pct > 0
        and config.breakeven_buffer_pct >= config.breakeven_ratchet_activation_pct
    ):
        raise ValueError(
            "breakeven_buffer_pct must be below breakeven_ratchet_activation_pct."
        )


def _validate_observations(config: TradingBotConfig) -> None:
    """Record-only observation lists (rc.3, rc.5) must stay bounded."""
    from pumpfun_trading.strategies.graduation import GRADUATION_REAL_SOL

    if not 0.0 <= config.screen_reject_sample_pct <= 1.0:
        raise ValueError("screen_reject_sample_pct must be between 0 and 1.")
    if config.screen_reject_sample_max_mints < 0:
        raise ValueError("screen_reject_sample_max_mints must not be negative.")
    if config.screen_reject_sample_ttl_seconds <= 0:
        raise ValueError("screen_reject_sample_ttl_seconds must be greater than zero.")
    if config.graduation_discovery_scan_seconds < 0:
        raise ValueError("graduation_discovery_scan_seconds must not be negative.")
    if (
        0 < config.graduation_discovery_scan_seconds
        and config.graduation_discovery_scan_seconds < 10.0
    ):
        raise ValueError(
            "graduation_discovery_scan_seconds must be 0 (off) or at least 10."
        )
    if not 0.0 < config.graduation_discovery_min_real_sol < GRADUATION_REAL_SOL:
        raise ValueError(
            "graduation_discovery_min_real_sol must be between 0 and the "
            f"graduation reserve ({GRADUATION_REAL_SOL:g} SOL)."
        )
    if config.graduation_discovery_max_mints < 0:
        raise ValueError("graduation_discovery_max_mints must not be negative.")
    if config.graduation_discovery_ttl_seconds <= 0:
        raise ValueError("graduation_discovery_ttl_seconds must be greater than zero.")
    if config.observation_poll_interval_seconds < 1.0:
        raise ValueError("observation_poll_interval_seconds must be at least 1.")
    if not 0.0 <= config.launch_sample_pct <= 1.0:
        raise ValueError("launch_sample_pct must be between 0 and 1.")
    if config.launch_sample_max_mints < 0:
        raise ValueError("launch_sample_max_mints must not be negative.")
    if config.launch_sample_ttl_seconds <= 0:
        raise ValueError("launch_sample_ttl_seconds must be greater than zero.")
    if config.launch_sample_poll_interval_seconds < 1.0:
        raise ValueError("launch_sample_poll_interval_seconds must be at least 1.")
    if config.launch_sample_extend_seconds < 0 or (
        0 < config.launch_sample_extend_seconds <= config.launch_sample_ttl_seconds
    ):
        raise ValueError(
            "launch_sample_extend_seconds must be 0 (off) or longer than "
            "launch_sample_ttl_seconds."
        )
    if config.launch_sample_extend_min_real_sol < 0:
        raise ValueError("launch_sample_extend_min_real_sol must not be negative.")
    if config.launch_sample_extend_poll_interval_seconds < 1.0:
        raise ValueError(
            "launch_sample_extend_poll_interval_seconds must be at least 1."
        )
    if config.post_exit_observation_seconds < 0:
        raise ValueError("post_exit_observation_seconds must not be negative.")
    if config.post_exit_max_mints < 0:
        raise ValueError("post_exit_max_mints must not be negative.")
    if config.post_exit_poll_interval_seconds < 1.0:
        raise ValueError("post_exit_poll_interval_seconds must be at least 1.")
    if config.graduation_observation_seconds < 0:
        raise ValueError("graduation_observation_seconds must not be negative.")
    if config.graduation_observation_max_mints < 0:
        raise ValueError("graduation_observation_max_mints must not be negative.")
    if config.graduation_observation_poll_interval_seconds < 1.0:
        raise ValueError(
            "graduation_observation_poll_interval_seconds must be at least 1."
        )
    if config.graduation_observation_fast_seconds < 0:
        raise ValueError("graduation_observation_fast_seconds must not be negative.")
    if config.graduation_observation_fast_poll_interval_seconds < 1.0:
        raise ValueError(
            "graduation_observation_fast_poll_interval_seconds must be at least 1."
        )


__all__ = [
    "DEFAULT_PRESETS",
    "CONFIG_ALIASES",
    "normalize_config_dict",
    "resolve_strategy_config",
]
