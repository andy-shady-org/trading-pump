"""Unit tests for ``strategies/presets.py``."""

from __future__ import annotations

import json

import pytest

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config
from pumpfun_trading.tests.support.factories import make_config


def test_strategy_presets_circuit_breaker_config():
    cons = resolve_strategy_config("conservative")
    assert cons.max_daily_drawdown_pct == 0.15
    assert cons.emergency_hard_lock_hours == 24.0
    assert cons.auto_liquidate_on_circuit_breaker is True

    bal = resolve_strategy_config("balanced")
    assert bal.max_daily_drawdown_pct == 0.20
    assert bal.emergency_hard_lock_hours == 24.0
    assert bal.auto_liquidate_on_circuit_breaker is True

    agg = resolve_strategy_config("aggressive")
    assert agg.max_daily_drawdown_pct == 0.25
    assert agg.emergency_hard_lock_hours == 12.0
    assert agg.auto_liquidate_on_circuit_breaker is True


def test_strategy_presets_and_custom_overrides():
    for preset_name in ["conservative", "balanced", "aggressive"]:
        preset_cfg = resolve_strategy_config(preset_name)
        assert preset_cfg.enable_trailing_stop is True
        assert preset_cfg.enable_tiered_take_profit is True
        assert preset_cfg.tier_1_take_profit > 1.0
        assert preset_cfg.tier_2_take_profit > preset_cfg.tier_1_take_profit

    # Custom override
    custom_cfg = resolve_strategy_config(
        "balanced",
        overrides={
            "enable_trailing_stop": False,
            "tier_1_take_profit": 2.2,
        },
    )
    assert custom_cfg.enable_trailing_stop is False
    assert custom_cfg.tier_1_take_profit == 2.2


def test_preset_stagnant_and_max_hold_configs():
    """Verify preset definitions configure stagnant and max hold limits properly."""
    cfg_cons = resolve_strategy_config("conservative")
    assert cfg_cons.enable_stagnant_exit is True
    assert cfg_cons.stagnant_timeout_seconds == 180.0
    assert cfg_cons.max_hold_time_seconds == 900.0

    cfg_bal = resolve_strategy_config("balanced")
    assert cfg_bal.enable_stagnant_exit is True
    assert cfg_bal.stagnant_timeout_seconds == 120.0
    assert cfg_bal.max_hold_time_seconds == 600.0

    cfg_agg = resolve_strategy_config("aggressive")
    assert cfg_agg.enable_stagnant_exit is True
    assert cfg_agg.stagnant_timeout_seconds == 60.0
    assert cfg_agg.max_hold_time_seconds == 300.0


def test_strategy_preset_validation_and_fallbacks():
    config = resolve_strategy_config("balanced")
    assert config.strategy_preset == "balanced"
    assert resolve_strategy_config("unknown").strategy_preset == "balanced"

    overridden = resolve_strategy_config(
        "balanced",
        overrides={"max_active_positions": 2, "take_profit": 1.8, "stop_loss": 0.75},
    )
    assert overridden.max_active_positions == 2
    assert overridden.take_profit == 1.8

    with pytest.raises(ValueError, match="greater than zero"):
        resolve_strategy_config("balanced", overrides={"buy_amount_sol": 0})

    with pytest.raises(ValueError, match="less than take_profit"):
        resolve_strategy_config(
            "balanced",
            overrides={"take_profit": 1.2, "stop_loss": 1.3},
        )

    with pytest.raises(ValueError, match="at least 1"):
        resolve_strategy_config("balanced", overrides={"max_active_positions": 0})


def test_strategy_presets_momentum_configuration():
    conservative = resolve_strategy_config("conservative")
    assert conservative.enable_momentum_signals is True
    assert conservative.momentum_min_z_score == 3.0
    assert conservative.momentum_min_buy_ratio == 4.0
    assert conservative.momentum_min_unique_buyers == 5
    assert conservative.momentum_min_net_inflow_sol == 1.0

    balanced = resolve_strategy_config("balanced")
    assert balanced.enable_momentum_signals is True
    assert balanced.momentum_min_z_score == 2.5
    assert balanced.momentum_min_buy_ratio == 3.0
    assert balanced.momentum_min_unique_buyers == 3
    assert balanced.momentum_min_net_inflow_sol == 0.5

    aggressive = resolve_strategy_config("aggressive")
    assert aggressive.enable_momentum_signals is True
    assert aggressive.momentum_min_z_score == 2.0
    assert aggressive.momentum_min_buy_ratio == 2.0
    assert aggressive.momentum_min_unique_buyers == 2
    assert aggressive.momentum_min_net_inflow_sol == 0.25


def test_config_aliases_and_normalization(tmp_path):
    from pumpfun_trading.strategies.presets import (
        normalize_config_dict,
        resolve_strategy_config,
    )

    alias_input = {
        "stagnant_curve_timeout_seconds": 45.0,
        "take_profit_tier1_multiplier": 1.45,
        "take_profit_tier1_pct": 0.35,
        "take_profit_tier2_multiplier": 2.50,
        "take_profit_tier2_pct": 0.35,
        "stop_loss_pct": 0.85,
        "max_creator_initial_pct": 0.08,
        "min_order_flow_buyers": 3,
        "dynamic_slippage_enabled": True,
        "anti_rug_filters_enabled": True,
        "capital_rotation_enabled": True,
        "pre_graduation_harvesting_enabled": True,
        "cross_venue_arbitrage_enabled": True,
        "mempool_backrunning_enabled": True,
        "cluster_analysis_enabled": True,
        "copy_trading_enabled": True,
        "momentum_signals_enabled": True,
        "raydium_migration_sniping_enabled": True,
        "tiered_take_profit_enabled": True,
        "trailing_stop_enabled": True,
        "stagnant_exit_enabled": True,
        "max_hold_timeout_enabled": True,
    }

    normalized = normalize_config_dict(alias_input)
    assert normalized["stagnant_timeout_seconds"] == 45.0
    assert normalized["tier_1_take_profit"] == 1.45
    assert normalized["tier_1_sell_fraction"] == 0.35
    assert normalized["tier_2_take_profit"] == 2.50
    assert normalized["tier_2_sell_fraction"] == 0.35
    assert normalized["stop_loss"] == 0.85
    assert normalized["max_creator_initial_holding_pct"] == 0.08
    assert normalized["momentum_min_unique_buyers"] == 3
    assert normalized["enable_dynamic_slippage"] is True
    assert normalized["enable_anti_rug_filters"] is True
    assert normalized["enable_capital_rotation"] is True
    assert normalized["enable_pre_graduation_harvesting"] is True
    assert normalized["enable_cross_venue_arbitrage"] is True
    assert normalized["enable_mempool_backrunning"] is True
    assert normalized["enable_cluster_analysis"] is True
    assert normalized["enable_copy_trading"] is True
    assert normalized["enable_momentum_signals"] is True
    assert normalized["enable_raydium_migration_sniping"] is True
    assert normalized["enable_tiered_take_profit"] is True
    assert normalized["enable_trailing_stop"] is True
    assert normalized["enable_stagnant_exit"] is True
    assert normalized["enable_max_hold_timeout"] is True

    # Test resolve_strategy_config with alias overrides
    cfg = resolve_strategy_config("balanced", overrides=alias_input)
    assert cfg.stagnant_timeout_seconds == 45.0
    assert cfg.tier_1_take_profit == 1.45
    assert cfg.tier_1_sell_fraction == 0.35
    assert cfg.tier_2_take_profit == 2.50
    assert cfg.tier_2_sell_fraction == 0.35
    assert cfg.stop_loss == 0.85
    assert cfg.max_creator_initial_holding_pct == 0.08
    assert cfg.momentum_min_unique_buyers == 3

    # Test TradingBotConfig.from_dict
    cfg_from_dict = TradingBotConfig.from_dict(alias_input)
    assert cfg_from_dict.stagnant_timeout_seconds == 45.0
    assert cfg_from_dict.tier_1_take_profit == 1.45

    # Test TradingBotConfig.from_file
    json_path = tmp_path / "test_config_aliases.json"
    json_path.write_text(json.dumps(alias_input), encoding="utf-8")
    cfg_from_file = TradingBotConfig.from_file(json_path)
    assert cfg_from_file.stagnant_timeout_seconds == 45.0
    assert cfg_from_file.tier_1_take_profit == 1.45
    assert cfg_from_file.tier_2_take_profit == 2.50
    assert cfg_from_file.stop_loss == 0.85


def test_strategy_config_and_presets_integration() -> None:
    """Verify TradingBotConfig arbitrage fields and preset calibrations."""
    cfg = make_config(
        dry_run=False,
        enable_cross_venue_arbitrage=True,
        enable_mempool_backrunning=True,
        min_arbitrage_profit_sol=0.004,
        min_arbitrage_spread_pct=0.02,
        max_arbitrage_input_sol=0.75,
        min_arbitrage_input_sol=0.02,
        arbitrage_jito_tip_profit_share_pct=0.45,
    )
    assert cfg.enable_cross_venue_arbitrage is True
    assert cfg.min_arbitrage_profit_sol == 0.004
    d = cfg.to_dict()
    assert d["enable_cross_venue_arbitrage"] is True
    assert d["max_arbitrage_input_sol"] == 0.75

    # Check presets
    cons = resolve_strategy_config("conservative")
    assert cons.enable_cross_venue_arbitrage is True
    assert cons.min_arbitrage_spread_pct == 0.020

    bal = resolve_strategy_config("balanced")
    assert bal.enable_cross_venue_arbitrage is True
    assert bal.min_arbitrage_spread_pct == 0.015

    agg = resolve_strategy_config("aggressive")
    assert agg.enable_cross_venue_arbitrage is True
    assert agg.min_arbitrage_spread_pct == 0.010


def test_presets_validation_exceptions():
    # buy_amount_sol <= 0
    with pytest.raises(ValueError, match="buy_amount_sol"):
        resolve_strategy_config("balanced", overrides={"buy_amount_sol": 0.0})

    # stop_loss >= take_profit
    with pytest.raises(ValueError, match="stop_loss must be less than take_profit"):
        resolve_strategy_config(
            "balanced", overrides={"stop_loss": 2.5, "take_profit": 2.0}
        )

    # max_active_positions < 1
    with pytest.raises(ValueError, match="max_active_positions"):
        resolve_strategy_config("balanced", overrides={"max_active_positions": 0})

    # stagnant_timeout_seconds <= 0
    with pytest.raises(ValueError, match="stagnant_timeout_seconds"):
        resolve_strategy_config("balanced", overrides={"stagnant_timeout_seconds": 0.0})

    # max_hold_time_seconds <= 0
    with pytest.raises(ValueError, match="max_hold_time_seconds"):
        resolve_strategy_config("balanced", overrides={"max_hold_time_seconds": 0.0})

    # invalid drawdown_reference_mode
    with pytest.raises(ValueError, match="Invalid drawdown_reference_mode"):
        resolve_strategy_config(
            "balanced", overrides={"drawdown_reference_mode": "invalid_mode"}
        )

    # profit_ratchet_ratio out of bounds
    with pytest.raises(ValueError, match="profit_ratchet_ratio"):
        resolve_strategy_config("balanced", overrides={"profit_ratchet_ratio": 1.5})

    # profit_drawdown_tolerance_pct out of bounds
    with pytest.raises(ValueError, match="profit_drawdown_tolerance_pct"):
        resolve_strategy_config(
            "balanced", overrides={"profit_drawdown_tolerance_pct": 0.0}
        )

    # invalid log_rotation_type
    with pytest.raises(ValueError, match="Invalid log_rotation_type"):
        resolve_strategy_config(
            "balanced", overrides={"log_rotation_type": "invalid_rot"}
        )

    # invalid slippage bounds
    with pytest.raises(ValueError, match="Invalid slippage bounds"):
        resolve_strategy_config(
            "balanced", overrides={"min_slippage_bps": 500, "max_slippage_bps": 200}
        )

    # cluster concentration bounds
    with pytest.raises(ValueError, match="max_cluster_concentration_pct"):
        resolve_strategy_config(
            "balanced", overrides={"max_cluster_concentration_pct": -0.1}
        )

    with pytest.raises(ValueError, match="max_single_cluster_pct"):
        resolve_strategy_config("balanced", overrides={"max_single_cluster_pct": 1.5})

    with pytest.raises(ValueError, match="max_sybil_wash_ratio"):
        resolve_strategy_config("balanced", overrides={"max_sybil_wash_ratio": -0.5})

    with pytest.raises(ValueError, match="cluster_trace_depth"):
        resolve_strategy_config("balanced", overrides={"cluster_trace_depth": 0})
