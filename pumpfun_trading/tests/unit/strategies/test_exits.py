"""Unit tests for ``strategies/exits.py``."""

from __future__ import annotations

import pytest

from pumpfun_trading.bot.strategy import (
    ExitAction,
    PositionExitState,
    TradingBotConfig,
    TradingStrategy,
    evaluate_exit_strategy,
    resolve_strategy_config,
    should_exit_position,
    update_position_peak,
)
from pumpfun_trading.tests.support.factories import make_config


def test_position_exit_state_model():
    state = PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )

    assert state.performance == 1.0
    assert state.peak_performance == 1.0
    assert state.drawdown_from_peak == 0.0
    assert not state.trailing_stop_active
    assert not state.tier_1_executed
    assert not state.tier_2_executed
    assert not state.moonbag_active

    # Update to higher price
    state.update_price(60.0)
    assert state.current_market_cap == 60.0
    assert state.peak_market_cap == 60.0
    assert state.performance == 2.0
    assert state.peak_performance == 2.0
    assert state.drawdown_from_peak == 0.0

    # Retracement
    state.update_price(51.0)
    assert state.current_market_cap == 51.0
    assert state.peak_market_cap == 60.0
    assert state.performance == 1.7
    assert state.peak_performance == 2.0
    assert pytest.approx(state.drawdown_from_peak, 0.001) == 0.15

    # Partial exit recording
    state.record_partial_exit(tier=1, sold_tokens=500_000)
    assert state.tier_1_executed
    assert state.remaining_token_amount == 500_000

    state.record_partial_exit(tier=2, sold_tokens=250_000)
    assert state.tier_2_executed
    assert state.moonbag_active
    assert state.remaining_token_amount == 250_000

    # Serialization roundtrip
    serialized = state.to_dict()
    assert serialized["remaining_token_amount"] == 250_000
    assert serialized["tier_1_executed"]
    assert serialized["tier_2_executed"]

    restored = PositionExitState.from_dict(serialized)
    assert restored.entry_market_cap == 30.0
    assert restored.remaining_token_amount == 250_000
    assert restored.moonbag_active


def test_position_exit_state_zero_and_fallback():
    zero_state = PositionExitState(
        entry_market_cap=0.0,
        current_market_cap=0.0,
        peak_market_cap=0.0,
        initial_token_amount=0,
        remaining_token_amount=0,
    )
    assert zero_state.performance == 1.0
    assert zero_state.peak_performance == 1.0
    assert zero_state.drawdown_from_peak == 0.0

    # Fallback from bare dict
    raw = {"entry_market_cap": 25.0, "token_amount": 500}
    from_dict_state = PositionExitState.from_dict(raw)
    assert from_dict_state.entry_market_cap == 25.0
    assert from_dict_state.initial_token_amount == 500
    assert from_dict_state.remaining_token_amount == 500


def test_update_position_peak():
    # Test on dict position
    pos_dict = {"entry_market_cap": 10.0, "current_market_cap": 10.0}
    peak = update_position_peak(pos_dict, 15.0)
    assert peak == 15.0
    assert pos_dict["peak_market_cap"] == 15.0
    assert pos_dict["current_market_cap"] == 15.0

    # Price declines: peak remains 15.0
    peak_declined = update_position_peak(pos_dict, 12.0)
    assert peak_declined == 15.0
    assert pos_dict["current_market_cap"] == 12.0

    # Test on PositionExitState
    state = PositionExitState(10.0, 10.0, 10.0, 100, 100)
    peak_state = update_position_peak(state, 20.0)
    assert peak_state == 20.0
    assert state.peak_market_cap == 20.0


def test_evaluate_exit_strategy_stop_loss():
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=100.0,
        current_market_cap=80.0,
        peak_market_cap=100.0,
        initial_token_amount=1_000,
        remaining_token_amount=1_000,
    )

    decision = evaluate_exit_strategy(config, state, current_market_cap=80.0)
    assert decision.action == ExitAction.FULL_EXIT
    assert decision.exit_type == "stop_loss"
    assert decision.sell_tokens == 1_000
    assert "stop_loss_hit" in decision.reason


def test_evaluate_exit_strategy_tiered_take_profit():
    config = resolve_strategy_config("balanced")  # tier_1=2.0x, tier_2=3.5x
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=10.0,
        peak_market_cap=10.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )

    # 1. At 1.8x -> hold (under 2.0x tier 1)
    decision = evaluate_exit_strategy(config, state, current_market_cap=18.0)
    assert decision.action == ExitAction.HOLD

    # 2. At 2.0x -> Tier 1 partial exit (sell 50% = 500,000 tokens)
    decision_t1 = evaluate_exit_strategy(config, state, current_market_cap=20.0)
    assert decision_t1.action == ExitAction.PARTIAL_EXIT
    assert decision_t1.exit_type == "tier_1"
    assert decision_t1.target_tier == 1
    assert decision_t1.sell_tokens == 500_000

    # Record Tier 1 fill
    state.record_partial_exit(tier=1, sold_tokens=decision_t1.sell_tokens)
    assert state.tier_1_executed
    assert state.remaining_token_amount == 500_000

    # 3. At 3.0x -> Hold waiting for Tier 2 (3.5x)
    decision_hold = evaluate_exit_strategy(config, state, current_market_cap=30.0)
    assert decision_hold.action == ExitAction.HOLD

    # 4. At 3.5x -> Tier 2 partial exit (sell 25% of initial = 250,000 tokens)
    decision_t2 = evaluate_exit_strategy(config, state, current_market_cap=35.0)
    assert decision_t2.action == ExitAction.PARTIAL_EXIT
    assert decision_t2.exit_type == "tier_2"
    assert decision_t2.target_tier == 2
    assert decision_t2.sell_tokens == 250_000

    # Record Tier 2 fill
    state.record_partial_exit(tier=2, sold_tokens=decision_t2.sell_tokens)
    assert state.tier_2_executed
    assert state.moonbag_active
    assert state.remaining_token_amount == 250_000

    # 5. Moonbag floor trigger: price drops to 2.4x <= 2.5x floor
    decision_moonbag = evaluate_exit_strategy(config, state, current_market_cap=24.0)
    assert decision_moonbag.action == ExitAction.FULL_EXIT
    assert decision_moonbag.exit_type == "moonbag_floor"
    assert decision_moonbag.sell_tokens == 250_000


def test_evaluate_exit_strategy_trailing_stop():
    # Test trailing stop when tiered take profit is disabled or before tier hits
    config = make_config(
        dry_run=False,
        enable_tiered_take_profit=False,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.50,  # Activates at +50% (1.5x)
        trailing_stop_drop_pct=0.15,  # Exits if drops 15% from peak
        take_profit=3.0,
        stop_loss=0.85,
    )
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=10.0,
        peak_market_cap=10.0,
        initial_token_amount=10_000,
        remaining_token_amount=10_000,
    )

    # Price at 1.4x (+40%): Trailing stop not active yet
    d1 = evaluate_exit_strategy(config, state, current_market_cap=14.0)
    assert d1.action == ExitAction.HOLD
    assert not state.trailing_stop_active

    # Price reaches 1.6x (+60%): Trailing stop activates
    d2 = evaluate_exit_strategy(config, state, current_market_cap=16.0)
    assert d2.action == ExitAction.HOLD
    assert state.trailing_stop_active
    assert state.peak_market_cap == 16.0

    # Price climbs further to 2.0x: Peak updates to 20.0
    d3 = evaluate_exit_strategy(config, state, current_market_cap=20.0)
    assert d3.action == ExitAction.HOLD
    assert state.peak_market_cap == 20.0

    # Price drops to 18.0 (10% drop from 20.0): Retracement within tolerance (10% < 15%)
    d4 = evaluate_exit_strategy(config, state, current_market_cap=18.0)
    assert d4.action == ExitAction.HOLD

    # Price drops to 16.8 (16% drop from 20.0): Trailing stop triggers
    d5 = evaluate_exit_strategy(config, state, current_market_cap=16.8)
    assert d5.action == ExitAction.FULL_EXIT
    assert d5.exit_type == "trailing_stop"
    assert "trailing_stop_hit" in d5.reason
    assert d5.sell_tokens == 10_000


def test_evaluate_exit_strategy_low_balance_and_small_remainder():
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=20.0,
        peak_market_cap=20.0,
        initial_token_amount=10,
        remaining_token_amount=10,
    )

    # Small balance below min sell balance
    d_low = evaluate_exit_strategy(
        config, state, current_market_cap=20.0, token_balance=0
    )
    assert d_low.action == ExitAction.HOLD

    # Tier 1 with small balance where remainder <= min_sell_balance triggers FULL_EXIT
    d_small = evaluate_exit_strategy(
        config, state, current_market_cap=20.0, token_balance=2
    )
    assert d_small.action == ExitAction.FULL_EXIT
    assert d_small.target_tier == 1


def test_should_exit_position_compatibility():
    config = resolve_strategy_config("balanced")

    # Simple performance check without position state
    assert not should_exit_position(config, performance=1.1, token_balance=100)
    assert should_exit_position(config, performance=0.8, token_balance=100)
    assert should_exit_position(config, performance=2.0, token_balance=100)

    # With position state dict
    pos = {
        "entry_market_cap": 10.0,
        "current_market_cap": 20.0,
        "initial_token_amount": 1000,
        "remaining_token_amount": 1000,
    }
    assert should_exit_position(
        config,
        performance=2.0,
        token_balance=1000,
        position=pos,
        current_market_cap=20.0,
    )


def test_trading_strategy_exit_and_peak_methods():
    config = resolve_strategy_config("conservative")
    strat = TradingStrategy(config)

    pos = {
        "entry_market_cap": 10.0,
        "current_market_cap": 10.0,
        "initial_token_amount": 500,
        "remaining_token_amount": 500,
    }

    # Update peak
    peak = strat.update_peak(pos, 15.0)
    assert peak == 15.0

    # Evaluate exit
    decision = strat.evaluate_exit(pos, current_market_cap=18.0, token_balance=500)
    assert decision.action == ExitAction.PARTIAL_EXIT
    assert decision.exit_type == "tier_1"

    # Strategy summary
    summary = strat.summary()
    assert summary["enable_trailing_stop"] is True
    assert summary["enable_tiered_take_profit"] is True
    assert summary["tier_1_take_profit"] == 1.8


def test_exits_and_decision_additional_branches(tmp_path):
    # Test Tier 2 full exit when remaining units <= min_sell_balance
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=35.0,
        peak_market_cap=35.0,
        initial_token_amount=100,
        remaining_token_amount=25,
        tier_1_executed=True,
    )
    # Tier 2 triggers full exit because remainder is 0 <= min_sell_balance (1)
    d_t2_full = evaluate_exit_strategy(config, state, current_market_cap=35.0)
    assert d_t2_full.action == ExitAction.FULL_EXIT
    assert d_t2_full.exit_type == "tier_2"
    assert d_t2_full.target_tier == 2

    # Moonbag active but price is above floor -> HOLD
    state.record_partial_exit(tier=2, sold_tokens=25)
    assert state.moonbag_active
    d_moonbag_hold = evaluate_exit_strategy(
        config, state, current_market_cap=30.0, token_balance=50
    )
    assert d_moonbag_hold.action == ExitAction.HOLD

    # Standard take profit when tiered take profit is disabled
    cfg_no_tier = make_config(
        dry_run=False,
        enable_tiered_take_profit=False,
        enable_trailing_stop=False,
        take_profit=1.5,
        stop_loss=0.85,
    )
    state_no_tier = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=16.0,
        peak_market_cap=16.0,
        initial_token_amount=100,
        remaining_token_amount=100,
    )
    d_std_tp = evaluate_exit_strategy(cfg_no_tier, state_no_tier)
    assert d_std_tp.action == ExitAction.FULL_EXIT
    assert d_std_tp.exit_type == "take_profit"

    # Test TradingStrategy.is_eligible_for_buy and validate_risk
    strat = TradingStrategy(config)
    assert strat.is_eligible_for_buy(
        market_cap_sol=20.0, mint_seen_recently=False, buy_attempts=0
    )
    assert not strat.is_eligible_for_buy(
        market_cap_sol=1.0, mint_seen_recently=False, buy_attempts=0
    )
    assert strat.validate_risk(current_positions={}, proposed_entry_sol=0.01)

    # Test TradingBotConfig.from_file
    config_file = tmp_path / "bot_cfg.json"
    config_file.write_text(
        '{"preset": "conservative", "buy_amount_sol": 0.008}', encoding="utf-8"
    )
    loaded_cfg = TradingBotConfig.from_file(config_file)
    assert loaded_cfg.buy_amount_sol == 0.008
    assert loaded_cfg.strategy_preset == "conservative"


@pytest.mark.regression("BUG-16")
def test_stagnant_curve_timeout_exit():
    """BUG-16: Stagnant bonding curves at 27.96 SOL with no price change must exit after timeout."""
    cfg = make_config(
        dry_run=False,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=600.0,
        stagnant_price_delta_threshold_pct=0.005,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )

    # 1. Under timeout (elapsed 60s < 120s) -> HOLD
    d_early = evaluate_exit_strategy(
        cfg, state, current_market_cap=27.96, now=t0 + 60.0
    )
    assert d_early.action == ExitAction.HOLD

    # 2. Reached timeout (elapsed 120.1s >= 120.0s) -> FULL_EXIT
    d_timeout = evaluate_exit_strategy(
        cfg, state, current_market_cap=27.96, now=t0 + 120.1
    )
    assert d_timeout.action == ExitAction.FULL_EXIT
    assert d_timeout.exit_type == "stagnant_timeout"
    assert "stagnant_curve_timeout" in d_timeout.reason
    assert d_timeout.sell_tokens == 1_000_000

    # 3. should_exit_position helper returns True
    assert (
        should_exit_position(
            cfg,
            performance=1.0,
            token_balance=1_000_000,
            position=state,
            current_market_cap=27.96,
            now=t0 + 120.1,
        )
        is True
    )


@pytest.mark.regression("BUG-16")
def test_stagnant_curve_price_movement_resets_timer():
    """BUG-16: Meaningful price changes reset last_price_change_at and prevent premature stagnation exits."""
    cfg = make_config(
        dry_run=False,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        stagnant_price_delta_threshold_pct=0.005,  # 0.5%
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )

    # At t = 1090s (90s elapsed), price moves from 27.96 to 30.0 SOL (+7.3% > 0.5%)
    t_move = t0 + 90.0
    d_move = evaluate_exit_strategy(cfg, state, current_market_cap=30.0, now=t_move)
    assert d_move.action == ExitAction.HOLD
    assert state.last_price_change_at == t_move
    assert state.last_price == 30.0

    # At t = 1150s (150s from start, but only 60s from price move) -> HOLD
    d_mid = evaluate_exit_strategy(cfg, state, current_market_cap=30.0, now=t0 + 150.0)
    assert d_mid.action == ExitAction.HOLD

    # At t = 1211s (121s after price move) -> Stagnant Exit triggers
    d_stagnant = evaluate_exit_strategy(
        cfg, state, current_market_cap=30.0, now=t_move + 121.0
    )
    assert d_stagnant.action == ExitAction.FULL_EXIT
    assert d_stagnant.exit_type == "stagnant_timeout"


@pytest.mark.regression("BUG-16")
def test_max_hold_duration_timeout_exit():
    """BUG-16: Positions exceeding max_hold_time_seconds must exit regardless of minor price movement."""
    cfg = make_config(
        dry_run=False,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=300.0,
        stagnant_price_delta_threshold_pct=0.005,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=30.0,
    )

    # Price moves frequently every 80 seconds, resetting stagnant timer:
    state.update_price(31.0, now=t0 + 80.0)
    state.update_price(32.0, now=t0 + 160.0)
    state.update_price(33.0, now=t0 + 240.0)

    # At t = 1280s (280s < 300s) -> HOLD (stagnant elapsed is 40s < 120s, max hold is 280s < 300s)
    d_hold = evaluate_exit_strategy(cfg, state, current_market_cap=33.0, now=t0 + 280.0)
    assert d_hold.action == ExitAction.HOLD

    # At t = 1301s (301s >= 300s max hold limit) -> FULL_EXIT (max_hold_timeout)
    d_max = evaluate_exit_strategy(cfg, state, current_market_cap=33.0, now=t0 + 301.0)
    assert d_max.action == ExitAction.FULL_EXIT
    assert d_max.exit_type == "max_hold_timeout"
    assert "max_hold_time_exceeded" in d_max.reason


def test_timeout_flags_disabled():
    """Disabled stagnant and max hold flags must not trigger timeout exits."""
    cfg = make_config(
        dry_run=False,
        enable_stagnant_exit=False,
        stagnant_timeout_seconds=60.0,
        enable_max_hold_timeout=False,
        max_hold_time_seconds=120.0,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )
    d = evaluate_exit_strategy(cfg, state, current_market_cap=27.96, now=t0 + 10_000.0)
    assert d.action == ExitAction.HOLD


def _tiered_config() -> TradingBotConfig:
    return make_config(
        enable_tiered_take_profit=True,
        enable_trailing_stop=False,
        enable_stagnant_exit=False,
        enable_max_hold_timeout=False,
        dry_run=True,
    )


@pytest.mark.regression("BUG-42")
def test_tier_1_latched_pending_until_fill():
    # BUG-42: a second evaluation before the fill must not re-issue tier 1
    config = _tiered_config()
    state = PositionExitState(30.0, 30.0, 30.0, 1_000_000, 1_000_000)
    first = evaluate_exit_strategy(config, state, current_market_cap=65.0, now=10.0)
    assert first.action == ExitAction.PARTIAL_EXIT and first.target_tier == 1
    second = evaluate_exit_strategy(config, state, current_market_cap=65.0, now=11.0)
    assert second.action == ExitAction.HOLD
    state.record_partial_exit(tier=1, sold_tokens=first.sell_tokens)
    assert state.tier_1_executed and not state.pending_exit_tiers


def test_tier_pending_survives_dict_roundtrip_and_strategy_writes_back():
    config = _tiered_config()
    strategy = TradingStrategy(config)
    pos = {
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "initial_token_amount": 1_000_000,
        "remaining_token_amount": 1_000_000,
    }
    first = strategy.evaluate_exit(pos, current_market_cap=65.0)
    assert first.target_tier == 1
    assert "tier_1" in pos["pending_exit_tiers"]
    assert (
        strategy.evaluate_exit(pos, current_market_cap=65.0).action == ExitAction.HOLD
    )


@pytest.mark.regression("BUG-76")
def test_zero_entry_market_cap_adopts_current_as_baseline():
    # BUG-76: stop-loss must be able to fire even if entry MC was unknown
    config = _tiered_config()
    state = PositionExitState(0.0, 0.0, 0.0, 1_000_000, 1_000_000)
    hold = evaluate_exit_strategy(config, state, current_market_cap=30.0)
    assert hold.action == ExitAction.HOLD
    assert state.entry_market_cap == 30.0
    stop = evaluate_exit_strategy(config, state, current_market_cap=20.0)
    assert stop.exit_type == "stop_loss"


@pytest.mark.regression("BUG-65")
def test_zero_remaining_is_not_replaced_by_phantom_balance():
    # BUG-65: remaining 0 stays 0 and produces no sell
    restored = PositionExitState.from_dict(
        {
            "entry_market_cap": 30.0,
            "initial_token_amount": 500,
            "remaining_token_amount": 0,
        }
    )
    assert restored.remaining_token_amount == 0
    dec = evaluate_exit_strategy(_tiered_config(), restored, current_market_cap=10.0)
    assert dec.action == ExitAction.HOLD and dec.reason == "no_remaining_balance"


@pytest.mark.regression("BUG-43")
def test_pre_graduation_staged_take_profit_tranches():
    config = make_config(
        dry_run=False,
        enable_pre_graduation_harvesting=True,
        enable_tiered_take_profit=False,
        take_profit=10.0,
        pre_graduation_tranches=(
            {"progress_pct": 0.92, "sell_fraction": 0.30},
            {"progress_pct": 0.97, "sell_fraction": 0.30},
        ),
        min_sell_balance=1000,
    )

    state = PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=35.0,
        peak_market_cap=35.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )

    # 1. At 80% progress -> Hold
    dec_80 = evaluate_exit_strategy(
        config, state, current_market_cap=35.0, curve_progress_pct=80.0
    )
    assert dec_80.action == ExitAction.HOLD

    # 2. At 92.5% progress -> Tranche 1 partial exit (30% of initial = 300,000 tokens)
    dec_92 = evaluate_exit_strategy(
        config, state, current_market_cap=75.0, curve_progress_pct=92.5
    )
    assert dec_92.action == ExitAction.PARTIAL_EXIT
    assert dec_92.sell_fraction == 0.30
    assert dec_92.sell_tokens == 300_000
    assert dec_92.exit_type == "pre_graduation_tranche"
    assert dec_92.target_tier == "pre_grad_1"

    # Simulate fill of tranche 1
    state.record_partial_exit(tier="pre_grad_1", sold_tokens=300_000)
    assert state.remaining_token_amount == 700_000

    # Repeating at 93% should not re-trigger tranche 1
    dec_93 = evaluate_exit_strategy(
        config, state, current_market_cap=76.0, curve_progress_pct=93.0
    )
    assert dec_93.action == ExitAction.HOLD

    # 3. At 97.5% progress -> Tranche 2 partial exit (30% of initial = 300,000 tokens)
    dec_97 = evaluate_exit_strategy(
        config, state, current_market_cap=82.0, curve_progress_pct=97.5
    )
    assert dec_97.action == ExitAction.PARTIAL_EXIT
    assert dec_97.sell_tokens == 300_000
    assert dec_97.target_tier == "pre_grad_2"

    # Simulate fill of tranche 2
    state.record_partial_exit(tier="pre_grad_2", sold_tokens=300_000)
    assert state.remaining_token_amount == 400_000  # 40% retained
    # Pre-grad tranches must not consume the 2.0x/3.5x take-profit ladder (BUG-43)
    assert state.tier_1_executed is False
    assert state.tier_2_executed is False
    assert state.moonbag_active is False
    assert state.executed_pre_grad_tranches == {0, 1}


def _harvest_config() -> TradingBotConfig:
    return make_config(
        dry_run=False,
        enable_pre_graduation_harvesting=True,
        enable_tiered_take_profit=False,
        enable_stagnant_exit=False,
        enable_max_hold_timeout=False,
        take_profit=10.0,
        pre_graduation_tranches=(
            {"progress_pct": 0.92, "sell_fraction": 0.30},
            {"progress_pct": 0.97, "sell_fraction": 0.30},
        ),
        min_sell_balance=1000,
    )


def _fresh_state() -> PositionExitState:
    return PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )


@pytest.mark.regression("BUG-38")
@pytest.mark.parametrize("progress", [0.92, 0.97, 1.0])
def test_pre_graduation_low_percent_progress_does_not_fire(progress):
    # BUG-38: 0.92-1.0 is ~1% curve progress, not 92-100%
    dec = evaluate_exit_strategy(
        _harvest_config(),
        _fresh_state(),
        current_market_cap=31.0,
        curve_progress_pct=progress,
    )
    assert dec.action == ExitAction.HOLD


@pytest.mark.regression("BUG-42")
def test_pre_graduation_tranche_pending_until_fill_then_retries():
    # BUG-42: a tranche emitted but never filled is not lost forever
    config = _harvest_config()
    state = _fresh_state()
    first = evaluate_exit_strategy(
        config, state, current_market_cap=31.0, curve_progress_pct=93.0, now=1000.0
    )
    assert first.target_tier == "pre_grad_1"
    assert 0 not in state.executed_pre_grad_tranches
    again = evaluate_exit_strategy(
        config, state, current_market_cap=31.0, curve_progress_pct=93.0, now=1001.0
    )
    assert again.action == ExitAction.HOLD
    retry = evaluate_exit_strategy(
        config, state, current_market_cap=31.0, curve_progress_pct=93.0, now=1100.0
    )
    assert retry.target_tier == "pre_grad_1"


# --- FEAT-52: exits for confirmed momentum entries -----------------------------------


def _momentum_state(entry_time: float = 1_000.0) -> PositionExitState:
    return PositionExitState(
        entry_market_cap=40.0,
        current_market_cap=40.0,
        peak_market_cap=40.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=entry_time,
        last_price_change_at=entry_time,
        last_price=40.0,
    )


def _momentum_config(**overrides: object) -> TradingBotConfig:
    base: dict[str, object] = {
        "entry_mode": "confirmed",
        "stagnant_timeout_seconds": 35.0,
        "stagnant_min_buy_sol": 0.1,
        "breakeven_ratchet_activation_pct": 0.25,
        "breakeven_buffer_pct": 0.05,
        "enable_max_hold_timeout": False,
        "enable_trailing_stop": False,
    }
    base.update(overrides)
    return make_config(**base)


def test_buy_flow_stagnation_exits_without_follow_on_buys() -> None:
    config = _momentum_config()
    state = _momentum_state()

    held = evaluate_exit_strategy(config, state, 41.0, now=1_020.0)
    assert held.action == ExitAction.HOLD

    state.last_qualifying_buy_at = 1_030.0  # a fresh buy resets the clock
    held = evaluate_exit_strategy(config, state, 42.0, now=1_060.0)
    assert held.action == ExitAction.HOLD

    # The price still moved, but no buyer of size arrived for 36 s.
    decision = evaluate_exit_strategy(config, state, 43.0, now=1_066.0)
    assert decision.action == ExitAction.FULL_EXIT
    assert decision.exit_type == "stagnant_buy_flow"
    assert decision.sell_tokens == 1_000_000


def test_breakeven_ratchet_moves_the_floor_after_activation() -> None:
    config = _momentum_config(stagnant_min_buy_sol=0.0)
    state = _momentum_state()

    assert evaluate_exit_strategy(config, state, 49.0, now=1_001.0).action == (
        ExitAction.HOLD
    )
    assert state.breakeven_floor_active is False
    assert evaluate_exit_strategy(config, state, 51.0, now=1_002.0).action == (
        ExitAction.HOLD
    )
    assert state.breakeven_floor_active is True

    decision = evaluate_exit_strategy(config, state, 41.5, now=1_003.0)
    assert decision.action == ExitAction.FULL_EXIT
    assert decision.exit_type == "breakeven_ratchet"

    data: dict[str, object] = {}
    state.write_back(data)
    assert data["breakeven_floor_active"] is True
    restored = PositionExitState.from_dict(
        {**state.to_dict(), "last_qualifying_buy_at": 1_002.5}
    )
    assert restored.breakeven_floor_active is True
    assert restored.last_qualifying_buy_at == 1_002.5


def test_momentum_exits_are_off_in_launch_mode() -> None:
    config = _momentum_config(entry_mode="launch", stagnant_timeout_seconds=500.0)
    state = _momentum_state()
    state.breakeven_floor_active = True

    decision = evaluate_exit_strategy(config, state, 41.0, now=1_100.0)

    assert decision.action == ExitAction.HOLD


@pytest.mark.parametrize(
    ("entry_mode", "expected"), [("confirmed", "full"), ("launch", "partial")]
)
def test_last_pre_graduation_tranche_sells_everything_in_confirmed_mode(
    entry_mode: str, expected: str
) -> None:
    """FEAT-53: nothing is held into migration on the confirmed lanes."""
    config = make_config(
        dry_run=False,
        entry_mode=entry_mode,
        enable_pre_graduation_harvesting=True,
        enable_tiered_take_profit=False,
        take_profit=10.0,
        pre_graduation_tranches=(
            {"progress_pct": 0.92, "sell_fraction": 0.30},
            {"progress_pct": 0.97, "sell_fraction": 0.30},
        ),
        min_sell_balance=1000,
    )
    state = PositionExitState(
        entry_market_cap=60.0,
        current_market_cap=75.0,
        peak_market_cap=75.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=700_000,
        executed_pre_grad_tranches={0},
    )
    decision = evaluate_exit_strategy(
        config, state, current_market_cap=80.0, curve_progress_pct=97.5
    )
    if expected == "full":
        assert decision.action == ExitAction.FULL_EXIT
        assert decision.sell_tokens == 700_000
    else:
        assert decision.action == ExitAction.PARTIAL_EXIT
        assert decision.sell_tokens == 300_000
    assert decision.target_tier == "pre_grad_2"
