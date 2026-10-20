from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pumpfun_trading.ops.redact import redact_url


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
    headless: bool = False
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
    # Reject a token outright when no holder data could be read (BUG-107).
    require_holder_data: bool = False
    # Reject a token with fewer holder accounts than this at screening (0 = off).
    # Counts the accounts getTokenLargestAccounts returned, bonding curve
    # included (max 20), i.e. the capture's ``holder_count``.
    min_holder_count: int = 0
    min_social_links_count: int = 1
    max_acceptable_risk_score: float = 50.0
    # Only buy Pump.fun launches: mint vanity suffix, stream pool and an existing
    # curve owned by the Pump.fun program (BUG-108).
    require_pump_mint_suffix: bool = True
    # Never buy a mint again once its position has been closed (BUG-109).
    allow_mint_reentry: bool = False
    # Paper fills pay for the screening/landing latency a live buy has: wait,
    # re-read the curve, then worsen the fill by this many bps.
    paper_entry_delay_seconds: float = 0.0
    paper_entry_slippage_bps: int = 0
    # Simulated wallet for paper/dry-run; 0 means reserve + 10 buys.
    paper_starting_balance_sol: float = 0.0
    # Re-price held positions from the curve this often, in their own task;
    # 0 falls back to the 5 s health loop (BUG-112).
    position_refresh_seconds: float = 1.0
    # Refuse new buys while the stream refuses token-trade subscriptions, so no
    # position is held without trade data (BUG-112).
    require_trade_feed: bool = True
    # Seconds between probe subscriptions while the trade-feed breaker is open
    # (PumpPortal refusing subscribeTokenTrade, usually an unfunded API key).
    trade_feed_probe_seconds: float = 300.0
    # Skip mayhem-mode launches: an agent trades their curve, whose reserves
    # then drift off the standard 30 SOL invariant (stream and curve flag).
    skip_mayhem_mode: bool = True
    screening_cache_ttl_seconds: int = 60
    # Entry pipeline (Phase 4c, FEAT-51): "launch" buys at the create event;
    # "confirmed" watches screened launches, polls their curves over RPC and
    # subscribes to trades only for mints whose curve grows.
    entry_mode: str = "launch"
    watch_ttl_seconds: float = 600.0
    watch_max_mints: int = 300
    watch_poll_interval_seconds: float = 2.0
    # Real SOL reserve growth (SOL) since a mint was watched before it gets a
    # billed trade subscription.
    watch_promote_min_sol_growth: float = 1.5
    watch_max_trade_subscriptions: int = 20
    enable_momentum_signals: bool = True
    momentum_window_seconds: int = 30
    momentum_min_buy_ratio: float = 3.0
    momentum_min_z_score: float = 2.5
    momentum_min_unique_buyers: int = 3
    momentum_min_net_inflow_sol: float = 0.5
    momentum_baseline_window_seconds: int = 300
    momentum_max_token_age_seconds: int = 1800
    # Confirmed momentum entries (FEAT-52): token-age floor and market-cap
    # ceiling of the entry band (``min_market_cap_sol`` is the floor).
    momentum_min_token_age_seconds: float = 60.0
    momentum_max_market_cap_sol: float = 75.0
    # Exits for confirmed entries: full exit without a buy of at least this size
    # within ``stagnant_timeout_seconds``; break-even floor once the gain
    # reached the activation level.
    stagnant_min_buy_sol: float = 0.1
    breakeven_ratchet_activation_pct: float = 0.25
    breakeven_buffer_pct: float = 0.05
    # Refuse a buy whose modelled fixed round-trip costs (network fees, tip,
    # unrefunded rent) exceed this share of the position (0 = off).
    max_entry_cost_share_pct: float = 0.10
    # Entry drift guard (momentum lane): skip the buy when the curve market cap
    # at the fill is more than this share above the signal's (0 = off). Live it
    # also caps the buy slippage at the remaining headroom.
    momentum_max_entry_drift_pct: float = 0.0
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
    replay_log_path: str | None = None
    drawdown_reference_mode: str = "adaptive_ratchet"
    profit_ratchet_ratio: float = 0.50
    profit_drawdown_tolerance_pct: float = 0.35
    enable_diagnostic_events: bool = True
    event_log_path: str = "events.jsonl"
    event_log_subsystems: tuple[str, ...] = (
        "stream",
        "screening",
        "strategy",
        "execution",
        "risk",
        "lifecycle",
    )
    log_file: str | None = "bot.log"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_rotation_type: str = "size"
    log_compress: bool = True
    audit_max_bytes: int = 10 * 1024 * 1024
    audit_backup_count: int = 10
    audit_retention_days: int = 30
    audit_compress: bool = True
    replay_max_bytes: int = 50 * 1024 * 1024
    replay_backup_count: int = 10
    replay_retention_days: int = 30
    replay_compress: bool = True
    retention_check_interval_seconds: float = 3600.0
    enable_dynamic_slippage: bool = True
    min_slippage_bps: int = 100
    max_slippage_bps: int = 500
    max_exit_slippage_bps: int = 5000
    # Close the token account on a full exit to recover its rent (BUG-96).
    close_token_account_on_full_exit: bool = True
    priority_fee_mode: str = "adaptive"
    volatility_slippage_multiplier: float = 1.0
    price_impact_slippage_multiplier: float = 1.0
    enable_capital_rotation: bool = True
    displacement_min_conviction_percentile: float = 0.95
    displacement_hurdle_rate_pct: float = 0.03
    min_hold_before_displacement_seconds: float = 45.0
    displacement_evaluation_interval_seconds: float = 2.0
    enable_pre_graduation_harvesting: bool = True
    pre_graduation_entry_progress_pct: float = 0.70
    pre_graduation_max_entry_progress_pct: float = 0.85
    pre_graduation_min_acceleration: float = 0.0
    pre_graduation_tranches: tuple[dict[str, Any], ...] = (
        {"progress_pct": 0.92, "sell_fraction": 0.30},
        {"progress_pct": 0.97, "sell_fraction": 0.30},
    )
    enable_cluster_analysis: bool = True
    max_cluster_concentration_pct: float = 0.25
    max_single_cluster_pct: float = 0.20
    max_sybil_wash_ratio: float = 0.20
    cluster_trace_depth: int = 2
    enable_cross_venue_arbitrage: bool = True
    enable_mempool_backrunning: bool = True
    min_arbitrage_profit_sol: float = 0.003
    min_arbitrage_spread_pct: float = 0.015
    max_arbitrage_input_sol: float = 0.50
    min_arbitrage_input_sol: float = 0.01
    arbitrage_jito_tip_profit_share_pct: float = 0.50
    # Unattended operation (Sprint 24D, FEAT-50): daily summary alert at this UTC
    # hour, and alerts when the stream/RPC stay degraded this long (0 = off).
    daily_summary_alert: bool = True
    daily_summary_hour_utc: int = 0
    degradation_alert_minutes: float = 5.0
    # Treasury profit sweep (FEAT-42): off by default. SOL above the floor
    # (never below reserve + max exposure + a fee buffer) goes to the destination.
    profit_sweep_enabled: bool = False
    profit_sweep_destination: str = ""
    profit_sweep_hot_floor_sol: float = 0.0
    profit_sweep_min_sol: float = 0.05
    profit_sweep_interval_seconds: float = 3600.0

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
            "headless": self.headless,
            "stream_url": redact_url(self.stream_url),
            "api_base_url": redact_url(self.api_base_url),
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
            "require_holder_data": self.require_holder_data,
            "min_holder_count": self.min_holder_count,
            "min_social_links_count": self.min_social_links_count,
            "max_acceptable_risk_score": self.max_acceptable_risk_score,
            "require_pump_mint_suffix": self.require_pump_mint_suffix,
            "allow_mint_reentry": self.allow_mint_reentry,
            "paper_entry_delay_seconds": self.paper_entry_delay_seconds,
            "paper_entry_slippage_bps": self.paper_entry_slippage_bps,
            "paper_starting_balance_sol": self.paper_starting_balance_sol,
            "position_refresh_seconds": self.position_refresh_seconds,
            "require_trade_feed": self.require_trade_feed,
            "trade_feed_probe_seconds": self.trade_feed_probe_seconds,
            "skip_mayhem_mode": self.skip_mayhem_mode,
            "screening_cache_ttl_seconds": self.screening_cache_ttl_seconds,
            "entry_mode": self.entry_mode,
            "watch_ttl_seconds": self.watch_ttl_seconds,
            "watch_max_mints": self.watch_max_mints,
            "watch_poll_interval_seconds": self.watch_poll_interval_seconds,
            "watch_promote_min_sol_growth": self.watch_promote_min_sol_growth,
            "watch_max_trade_subscriptions": self.watch_max_trade_subscriptions,
            "enable_momentum_signals": self.enable_momentum_signals,
            "momentum_window_seconds": self.momentum_window_seconds,
            "momentum_min_buy_ratio": self.momentum_min_buy_ratio,
            "momentum_min_z_score": self.momentum_min_z_score,
            "momentum_min_unique_buyers": self.momentum_min_unique_buyers,
            "momentum_min_net_inflow_sol": self.momentum_min_net_inflow_sol,
            "momentum_baseline_window_seconds": self.momentum_baseline_window_seconds,
            "momentum_max_token_age_seconds": self.momentum_max_token_age_seconds,
            "momentum_min_token_age_seconds": self.momentum_min_token_age_seconds,
            "momentum_max_market_cap_sol": self.momentum_max_market_cap_sol,
            "stagnant_min_buy_sol": self.stagnant_min_buy_sol,
            "breakeven_ratchet_activation_pct": self.breakeven_ratchet_activation_pct,
            "breakeven_buffer_pct": self.breakeven_buffer_pct,
            "max_entry_cost_share_pct": self.max_entry_cost_share_pct,
            "momentum_max_entry_drift_pct": self.momentum_max_entry_drift_pct,
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
            "rpc_endpoints": [redact_url(u) for u in self.rpc_endpoints],
            "rpc_pool_health_check_interval_seconds": self.rpc_pool_health_check_interval_seconds,
            "rpc_pool_circuit_breaker_threshold": self.rpc_pool_circuit_breaker_threshold,
            "rpc_pool_circuit_breaker_cooldown_seconds": self.rpc_pool_circuit_breaker_cooldown_seconds,
            "rpc_pool_broadcast_concurrency": self.rpc_pool_broadcast_concurrency,
            "replay_log_path": self.replay_log_path,
            "drawdown_reference_mode": self.drawdown_reference_mode,
            "profit_ratchet_ratio": self.profit_ratchet_ratio,
            "profit_drawdown_tolerance_pct": self.profit_drawdown_tolerance_pct,
            "enable_diagnostic_events": self.enable_diagnostic_events,
            "event_log_path": self.event_log_path,
            "event_log_subsystems": list(self.event_log_subsystems),
            "log_file": self.log_file,
            "log_max_bytes": self.log_max_bytes,
            "log_backup_count": self.log_backup_count,
            "log_rotation_type": self.log_rotation_type,
            "log_compress": self.log_compress,
            "audit_max_bytes": self.audit_max_bytes,
            "audit_backup_count": self.audit_backup_count,
            "audit_retention_days": self.audit_retention_days,
            "audit_compress": self.audit_compress,
            "replay_max_bytes": self.replay_max_bytes,
            "replay_backup_count": self.replay_backup_count,
            "replay_retention_days": self.replay_retention_days,
            "replay_compress": self.replay_compress,
            "retention_check_interval_seconds": self.retention_check_interval_seconds,
            "enable_dynamic_slippage": self.enable_dynamic_slippage,
            "close_token_account_on_full_exit": self.close_token_account_on_full_exit,
            "min_slippage_bps": self.min_slippage_bps,
            "max_slippage_bps": self.max_slippage_bps,
            "max_exit_slippage_bps": self.max_exit_slippage_bps,
            "priority_fee_mode": self.priority_fee_mode,
            "volatility_slippage_multiplier": self.volatility_slippage_multiplier,
            "price_impact_slippage_multiplier": self.price_impact_slippage_multiplier,
            "enable_capital_rotation": self.enable_capital_rotation,
            "displacement_min_conviction_percentile": self.displacement_min_conviction_percentile,
            "displacement_hurdle_rate_pct": self.displacement_hurdle_rate_pct,
            "min_hold_before_displacement_seconds": self.min_hold_before_displacement_seconds,
            "displacement_evaluation_interval_seconds": self.displacement_evaluation_interval_seconds,
            "enable_pre_graduation_harvesting": self.enable_pre_graduation_harvesting,
            "pre_graduation_entry_progress_pct": self.pre_graduation_entry_progress_pct,
            "pre_graduation_max_entry_progress_pct": self.pre_graduation_max_entry_progress_pct,
            "pre_graduation_min_acceleration": self.pre_graduation_min_acceleration,
            "pre_graduation_tranches": list(self.pre_graduation_tranches),
            "enable_cluster_analysis": self.enable_cluster_analysis,
            "max_cluster_concentration_pct": self.max_cluster_concentration_pct,
            "max_single_cluster_pct": self.max_single_cluster_pct,
            "max_sybil_wash_ratio": self.max_sybil_wash_ratio,
            "cluster_trace_depth": self.cluster_trace_depth,
            "enable_cross_venue_arbitrage": self.enable_cross_venue_arbitrage,
            "enable_mempool_backrunning": self.enable_mempool_backrunning,
            "min_arbitrage_profit_sol": self.min_arbitrage_profit_sol,
            "min_arbitrage_spread_pct": self.min_arbitrage_spread_pct,
            "max_arbitrage_input_sol": self.max_arbitrage_input_sol,
            "min_arbitrage_input_sol": self.min_arbitrage_input_sol,
            "arbitrage_jito_tip_profit_share_pct": self.arbitrage_jito_tip_profit_share_pct,
            "daily_summary_alert": self.daily_summary_alert,
            "daily_summary_hour_utc": self.daily_summary_hour_utc,
            "degradation_alert_minutes": self.degradation_alert_minutes,
            "profit_sweep_enabled": self.profit_sweep_enabled,
            "profit_sweep_destination": self.profit_sweep_destination,
            "profit_sweep_hot_floor_sol": self.profit_sweep_hot_floor_sol,
            "profit_sweep_min_sol": self.profit_sweep_min_sol,
            "profit_sweep_interval_seconds": self.profit_sweep_interval_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradingBotConfig":
        preset = str(data.get("strategy_preset") or data.get("preset") or "balanced")
        from pumpfun_trading.strategies.presets import resolve_strategy_config

        return resolve_strategy_config(
            preset,
            overrides={
                k: v for k, v in data.items() if k not in {"preset", "strategy_preset"}
            },
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "TradingBotConfig":
        config_path = Path(path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Config file {config_path} must contain a JSON object.")
        return cls.from_dict(raw)


__all__ = ["TradingBotConfig"]
