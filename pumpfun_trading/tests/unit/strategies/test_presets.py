"""Unit tests for ``strategies/presets.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config
from pumpfun_trading.strategies.shadow import parse_shadow_variants
from pumpfun_trading.tests.support.factories import make_config


def _non_default(value: object) -> object:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.125
    return value


@pytest.mark.regression("BUG-125")
def test_every_config_field_survives_a_config_file() -> None:
    """A field the resolver doesn't pass on is dropped without a word.

    ``profit_sweep_enabled``, the FEAT-50 alerts, ``replay_log_path`` and
    ``enable_pumpswap_exit`` were all ignored in a config file.
    """
    import dataclasses

    defaults = TradingBotConfig()
    skipped = {"strategy_preset", "copy_trading_wallets", "event_log_subsystems"}
    dropped = []
    for field in dataclasses.fields(TradingBotConfig):
        if field.name in skipped:
            continue
        default = getattr(defaults, field.name)
        if isinstance(default, (bool, int, float)):
            wanted: object = _non_default(default)
        elif isinstance(default, str) or default is None:
            wanted = "x-" + field.name
        else:
            continue
        try:
            resolved = resolve_strategy_config(
                "balanced", overrides={field.name: wanted}
            )
        except ValueError:
            continue  # validation refuses this value; the field is still read
        if getattr(resolved, field.name) != wanted:
            dropped.append(field.name)
    # Normalised / clamped on purpose, so a probe value comes back changed.
    normalised = {
        "entry_mode",
        "drawdown_reference_mode",
        "log_rotation_type",
        "priority_fee_mode",
        "stream_url",
        "api_base_url",
        "copy_trading_sizing_mode",
        "paper_entry_slippage_bps",
        "trade_feed_probe_seconds",
        "log_file",
        "event_log_path",
    }
    assert [name for name in dropped if name not in normalised] == []


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


@pytest.mark.regression("BUG-107")
def test_require_holder_data_is_off_by_default_and_overridable_from_json() -> None:
    assert resolve_strategy_config("conservative").require_holder_data is False

    config = TradingBotConfig.from_dict(
        {"strategy_preset": "conservative", "require_holder_data": True}
    )

    assert config.require_holder_data is True
    assert config.to_dict()["require_holder_data"] is True


@pytest.mark.regression("BUG-108")
def test_entry_hardening_keys_default_and_override_from_json() -> None:
    default = resolve_strategy_config("conservative")
    assert default.require_pump_mint_suffix is True
    assert default.allow_mint_reentry is False
    assert default.paper_entry_delay_seconds == 0.0
    assert default.paper_entry_slippage_bps == 0

    config = TradingBotConfig.from_dict(
        {
            "strategy_preset": "conservative",
            "require_pump_mint_suffix": False,
            "allow_mint_reentry": True,
            "paper_entry_delay_seconds": -1.0,
            "paper_entry_slippage_bps": 9_000,
        }
    )

    assert config.require_pump_mint_suffix is False
    assert config.allow_mint_reentry is True
    assert config.paper_entry_delay_seconds == 0.0
    assert config.paper_entry_slippage_bps == 5_000
    assert config.to_dict()["paper_entry_slippage_bps"] == 5_000


@pytest.mark.regression("BUG-126")
def test_paper_exit_slippage_defaults_off_clamps_and_is_set_for_momentum() -> None:
    assert resolve_strategy_config("conservative").paper_exit_slippage_bps == 0
    assert resolve_strategy_config("momentum").paper_exit_slippage_bps == 100

    high = TradingBotConfig.from_dict({"paper_exit_slippage_bps": 9_000})
    low = TradingBotConfig.from_dict({"paper_exit_slippage_bps": -5})

    assert high.paper_exit_slippage_bps == 5_000
    assert high.to_dict()["paper_exit_slippage_bps"] == 5_000
    assert low.paper_exit_slippage_bps == 0


def test_capture_keys_default_and_override_from_json() -> None:
    default = resolve_strategy_config("conservative")
    assert default.skip_mayhem_mode is True
    assert default.trade_feed_probe_seconds == 300.0
    assert default.paper_starting_balance_sol == 0.0

    config = TradingBotConfig.from_dict(
        {
            "strategy_preset": "conservative",
            "skip_mayhem_mode": False,
            "trade_feed_probe_seconds": 5,
            "paper_starting_balance_sol": -1,
        }
    )

    assert config.skip_mayhem_mode is False
    assert config.trade_feed_probe_seconds == 30.0  # floor: don't spam probes
    assert config.paper_starting_balance_sol == 0.0
    assert config.to_dict()["skip_mayhem_mode"] is False


def test_min_holder_count_defaults_off_and_loads_from_json() -> None:
    assert resolve_strategy_config("conservative").min_holder_count == 0

    config = TradingBotConfig.from_dict(
        {"strategy_preset": "conservative", "min_holder_count": 6}
    )

    assert config.min_holder_count == 6
    assert config.to_dict()["min_holder_count"] == 6
    negative = TradingBotConfig.from_dict({"min_holder_count": -3})
    assert negative.min_holder_count == 0


def test_entry_mode_defaults_to_launch_and_loads_watch_keys() -> None:
    default = resolve_strategy_config("balanced")
    assert default.entry_mode == "launch"
    assert default.watch_max_mints == 300

    config = TradingBotConfig.from_dict(
        {
            "strategy_preset": "conservative",
            "entry_mode": " Confirmed ",
            "watch_ttl_seconds": 300,
            "watch_max_mints": 50,
            "watch_poll_interval_seconds": 1.5,
            "watch_promote_min_sol_growth": 2.0,
            "watch_max_trade_subscriptions": 10,
        }
    )

    assert config.entry_mode == "confirmed"
    data = config.to_dict()
    assert data["watch_ttl_seconds"] == 300.0
    assert data["watch_max_mints"] == 50
    assert data["watch_poll_interval_seconds"] == 1.5
    assert data["watch_promote_min_sol_growth"] == 2.0
    assert data["watch_max_trade_subscriptions"] == 10


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"entry_mode": "snipe"}, "entry_mode"),
        ({"watch_ttl_seconds": 0}, "watch_ttl_seconds"),
        ({"watch_max_mints": 0}, "watch_max_mints"),
        ({"watch_poll_interval_seconds": 0.01}, "watch_poll_interval_seconds"),
        ({"watch_promote_min_sol_growth": -1}, "watch_promote_min_sol_growth"),
        ({"watch_max_trade_subscriptions": -1}, "watch_max_trade_subscriptions"),
        ({"near_graduation_max_mints": -1}, "near_graduation_max_mints"),
        ({"near_graduation_min_progress_pct": 1.0}, "near_graduation_min_progress"),
        ({"near_graduation_stall_seconds": 0}, "near_graduation_stall_seconds"),
        ({"near_graduation_ttl_seconds": 60.0}, "near_graduation_ttl_seconds"),
        ({"near_graduation_poll_interval_seconds": 0}, "near_graduation_poll"),
        ({"shadow_variants": [{"name": "x", "stop_loss": 0.5}]}, "unknown key"),
        ({"screen_reject_sample_pct": 1.5}, "screen_reject_sample_pct"),
        ({"screen_reject_sample_max_mints": -1}, "screen_reject_sample_max"),
        ({"screen_reject_sample_ttl_seconds": 0}, "screen_reject_sample_ttl"),
        ({"graduation_discovery_scan_seconds": -1}, "must not be negative"),
        ({"graduation_discovery_scan_seconds": 5}, "0 \\(off\\) or at least 10"),
        ({"graduation_discovery_min_real_sol": 90.0}, "graduation reserve"),
        ({"graduation_discovery_max_mints": -1}, "graduation_discovery_max"),
        ({"graduation_discovery_ttl_seconds": 0}, "graduation_discovery_ttl"),
        ({"observation_poll_interval_seconds": 0.5}, "observation_poll"),
        ({"launch_sample_pct": -0.1}, "launch_sample_pct"),
        ({"launch_sample_max_mints": -1}, "launch_sample_max_mints"),
        ({"launch_sample_ttl_seconds": 0}, "launch_sample_ttl_seconds"),
        ({"launch_sample_poll_interval_seconds": 0.5}, "launch_sample_poll"),
        ({"post_exit_observation_seconds": -1}, "post_exit_observation_seconds"),
        ({"post_exit_max_mints": -1}, "post_exit_max_mints"),
        ({"post_exit_poll_interval_seconds": 0.5}, "post_exit_poll"),
    ],
)
def test_invalid_watch_settings_fail_fast(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_strategy_config("balanced", overrides=override)


def test_near_graduation_set_curve_capture_and_shadow_variants_load() -> None:
    default = resolve_strategy_config("balanced")
    assert default.near_graduation_max_mints == 0  # off unless configured
    assert default.capture_curve_polls is True
    assert default.shadow_variants == ()

    config = TradingBotConfig.from_dict(
        {
            "near_graduation_max_mints": 50,
            "near_graduation_min_progress_pct": 0.4,
            "capture_curve_polls": False,
            "shadow_variants": [{"name": "b8", "momentum_min_unique_buyers": 8}],
        }
    )

    assert config.near_graduation_max_mints == 50
    assert config.capture_curve_polls is False
    data = config.to_dict()
    assert data["near_graduation_min_progress_pct"] == 0.4
    assert data["shadow_variants"] == [{"name": "b8", "momentum_min_unique_buyers": 8}]


def test_capture_config_records_curves_near_graduation_and_shadow_variants() -> None:
    raw = json.loads(
        (Path(__file__).parents[4] / "configs" / "capture.json").read_text()
    )
    config = TradingBotConfig.from_dict(raw)

    assert config.entry_mode == "confirmed"
    assert config.capture_curve_polls is True
    assert config.near_graduation_max_mints > 0
    names = [variant["name"] for variant in config.shadow_variants]
    assert "baseline" in names and len(names) == len(set(names))
    # rc.3: only the rules that beat a random cut on rc.2, the FEAT-61 filters
    # (no data before rc.3) and the trade-feed pullback; the curve pullbacks and
    # the FEAT-57/60 filters were dropped (STRATEGY-PIVOT.md 6.10).
    kinds = {variant.kind for variant in parse_shadow_variants(config.shadow_variants)}
    assert kinds == {"momentum", "pullback"}
    assert {"buyers6", "drift5", "feat56_diversity", "feat61_bundle_pct"} <= set(names)
    assert not {"buyers8", "feat57_round_trip", "feat60_burst"} & set(names)
    # Paper exits pay what replay charges (BUG-126).
    assert config.paper_exit_slippage_bps == 100
    assert config.stop_loss == 0.92
    # rc.3 record-only inputs: a sample of screen rejects and the stop overshoot.
    assert config.screen_reject_sample_pct == 0.2
    assert config.record_stop_crossings is True
    assert config.graduation_discovery_scan_seconds == 0.0
    # rc.5 (FEAT-72): a fifth of all launches from creation, and every closed
    # position for 15 minutes after the sell (record-only).
    assert config.launch_sample_pct == 0.2
    assert config.post_exit_observation_seconds == 900.0


def test_record_only_observations_are_off_by_default() -> None:
    config = resolve_strategy_config("balanced")
    assert config.screen_reject_sample_pct == 0.0
    assert config.graduation_discovery_scan_seconds == 0.0
    assert config.record_stop_crossings is False
    assert config.launch_sample_pct == 0.0
    assert config.post_exit_observation_seconds == 0.0
    data = TradingBotConfig.from_dict(
        {
            "screen_reject_sample_pct": 0.3,
            "record_stop_crossings": True,
            "launch_sample_pct": 0.25,
            "launch_sample_max_mints": 50,
            "launch_sample_ttl_seconds": 600.0,
            "launch_sample_poll_interval_seconds": 3.0,
            "post_exit_observation_seconds": 300.0,
            "post_exit_max_mints": 20,
            "post_exit_poll_interval_seconds": 1.0,
        }
    ).to_dict()
    assert data["screen_reject_sample_pct"] == 0.3
    assert data["record_stop_crossings"] is True
    assert (
        data["launch_sample_pct"],
        data["launch_sample_max_mints"],
        data["launch_sample_ttl_seconds"],
        data["launch_sample_poll_interval_seconds"],
    ) == (0.25, 50, 600.0, 3.0)
    assert (
        data["post_exit_observation_seconds"],
        data["post_exit_max_mints"],
        data["post_exit_poll_interval_seconds"],
    ) == (300.0, 20, 1.0)


def test_pre_graduation_pilot_config_isolates_the_lane() -> None:
    raw = json.loads(
        (Path(__file__).parents[4] / "configs" / "pregrad_pilot.json").read_text()
    )
    config = TradingBotConfig.from_dict(raw)

    assert config.paper_trade is True
    assert config.enable_pre_graduation_harvesting is True
    assert config.near_graduation_max_mints > 0
    # No momentum buys and no billed trade feed for watched mints.
    assert config.watch_max_trade_subscriptions == 0
    assert config.pre_graduation_entry_progress_pct < (
        config.pre_graduation_max_entry_progress_pct
    )
    # Every curve pullback lost on the rc.2 pilot, so none is logged for rc.3.
    assert config.shadow_variants == ()
    # The lane keeps its wider stop; the momentum 0.92 was not tested on it.
    assert config.stop_loss == 0.85
    assert config.paper_exit_slippage_bps == 100
    # rc.3: discovered curves past 40 SOL are recorded, never bought.
    assert config.graduation_discovery_scan_seconds == 30.0
    assert config.graduation_discovery_min_real_sol == 40.0
    assert config.screen_reject_sample_pct == 0.0
    assert config.record_stop_crossings is True
    # rc.5: the pilot follows its closed positions; the launch sample runs in
    # the capture instance only, so a pair of runs records it once.
    assert config.post_exit_observation_seconds == 900.0
    assert config.launch_sample_pct == 0.0


def test_momentum_preset_uses_confirmed_entries_at_canary_size() -> None:
    config = resolve_strategy_config("momentum")

    assert config.strategy_preset == "momentum"
    assert config.entry_mode == "confirmed"
    assert config.buy_amount_sol == 0.02
    assert config.min_market_cap_sol < config.momentum_max_market_cap_sol
    assert config.momentum_min_token_age_seconds == 20.0
    assert config.stagnant_min_buy_sol == 0.1
    # One position must fit the inherited caps, or the preset never buys.
    assert config.buy_amount_sol <= (
        config.max_token_concentration_pct * config.max_total_exposure_sol
    )
    # Unproven lanes stay off (RELEASE-GATE.md 3.5).
    assert config.enable_pre_graduation_harvesting is False
    assert config.enable_copy_trading is False
    assert config.enable_cross_venue_arbitrage is False


def test_entry_drift_guard_is_off_by_default_and_never_negative() -> None:
    assert resolve_strategy_config("balanced").momentum_max_entry_drift_pct == 0.0
    assert resolve_strategy_config("momentum").momentum_max_entry_drift_pct == 0.08

    config = TradingBotConfig.from_dict({"momentum_max_entry_drift_pct": -0.5})
    assert config.momentum_max_entry_drift_pct == 0.0
    loaded = TradingBotConfig.from_dict({"momentum_max_entry_drift_pct": 0.1})
    assert loaded.to_dict()["momentum_max_entry_drift_pct"] == 0.1


def test_momentum_preset_matches_the_tuned_canary_config() -> None:
    canary = json.loads(
        (Path(__file__).parents[4] / "configs" / "canary.json").read_text()
    )
    preset = resolve_strategy_config("momentum")
    for key in (
        "entry_mode",
        "buy_amount_sol",
        "watch_promote_min_sol_growth",
        "momentum_min_unique_buyers",
        "momentum_min_net_inflow_sol",
        "momentum_min_token_age_seconds",
        "min_market_cap_sol",
        "momentum_max_market_cap_sol",
        "max_token_concentration_pct",
        "momentum_max_entry_drift_pct",
        "paper_exit_slippage_bps",
        "stop_loss",
    ):
        assert getattr(preset, key) == canary[key], key
    assert canary["enable_pre_graduation_harvesting"] is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"momentum_max_market_cap_sol": 30.0}, "momentum_max_market_cap_sol"),
        ({"momentum_min_token_age_seconds": 900.0}, "momentum_min_token_age_seconds"),
        ({"breakeven_buffer_pct": 0.3}, "breakeven_buffer_pct"),
    ],
)
def test_invalid_momentum_band_fails_fast_in_confirmed_mode(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_strategy_config("momentum", overrides=override)
    # The band is not validated for launch entries.
    resolve_strategy_config("momentum", overrides={**override, "entry_mode": "launch"})


@pytest.mark.regression("BUG-144")
def test_profit_ratchet_min_gain_default_and_bounds(tmp_path: Path) -> None:
    assert resolve_strategy_config("momentum").profit_ratchet_min_gain_pct == 0.02
    path = tmp_path / "cfg.json"
    path.write_text(
        json.dumps(
            {"strategy_preset": "momentum", "profit_ratchet_min_gain_pct": 0.05}
        ),
        encoding="utf-8",
    )
    assert TradingBotConfig.from_file(path).profit_ratchet_min_gain_pct == 0.05
    with pytest.raises(ValueError, match="profit_ratchet_min_gain_pct"):
        resolve_strategy_config(
            "balanced", overrides={"profit_ratchet_min_gain_pct": 1.5}
        )
