from __future__ import annotations

import pytest

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import (
    ExitAction,
    PositionExitState,
    evaluate_exit_strategy,
)
from pumpfun_trading.strategies.graduation import (
    GraduationEngine,
    GraduationTracker,
    GraduationTrajectory,
)


def test_graduation_acceleration_and_trajectory_classification():
    mint = "GradMint1111111111111111111111111111111111"
    tracker = GraduationTracker(
        mint=mint,
        target_graduation_sol=85.0,
        real_sol_reserves=50.0,
        timestamp=1000.0,
    )

    # 1. Steady accumulation: 50 -> 60 -> 70 SOL
    tracker.update_reserves(
        real_sol_reserves=55.0,
        virtual_sol_reserves=35.0,
        market_cap_sol=55.0,
        timestamp=1010.0,
    )
    tracker.update_reserves(
        real_sol_reserves=62.0,
        virtual_sol_reserves=37.0,
        market_cap_sol=62.0,
        timestamp=1020.0,
    )

    vel, accel = tracker.calculate_acceleration(
        window_seconds=30.0, current_time=1020.0
    )
    assert vel > 0.0
    assert accel >= 0.0

    traj_organic = tracker.classify_trajectory(current_time=1020.0, unique_buyers=5)
    assert isinstance(traj_organic, GraduationTrajectory)
    assert traj_organic.trajectory_type == "organic"
    assert traj_organic.progress_pct == pytest.approx((62.0 / 85.0) * 100.0, rel=1e-2)

    # 2. Syndicate sweep: massive single buy spike with 1 buyer
    tracker_sweep = GraduationTracker(
        mint="SweepMint222",
        target_graduation_sol=85.0,
        real_sol_reserves=50.0,
        timestamp=1000.0,
    )
    tracker_sweep.update_reserves(
        real_sol_reserves=75.0,
        virtual_sol_reserves=45.0,
        market_cap_sol=75.0,
        timestamp=1005.0,
    )
    traj_sweep = tracker_sweep.classify_trajectory(current_time=1005.0, unique_buyers=1)
    assert traj_sweep.trajectory_type == "syndicate_sweep"

    # 3. Volume exhaustion / selling retracement
    tracker_exhaust = GraduationTracker(
        mint="ExhaustMint333",
        target_graduation_sol=85.0,
        real_sol_reserves=65.0,
        timestamp=1000.0,
    )
    tracker_exhaust.update_reserves(
        real_sol_reserves=64.0,
        virtual_sol_reserves=40.0,
        market_cap_sol=64.0,
        timestamp=1010.0,
    )
    traj_exhaust = tracker_exhaust.classify_trajectory(
        current_time=1010.0, unique_buyers=1
    )
    assert traj_exhaust.trajectory_type == "exhaustion"
    assert traj_exhaust.recommended_action == "avoid"


def test_graduation_engine_pre_graduation_entry_signal():
    engine = GraduationEngine(target_graduation_sol=85.0)
    mint = "HarvestMint444"

    # Initially untracked
    sig_none = engine.evaluate_pre_graduation_harvesting_entry(mint)
    assert not sig_none.triggered

    # Track below 70% progress (e.g. 50 SOL / 85 SOL = 58.8%)
    engine.update_bonding_curve(
        mint=mint,
        bonding_curve="CurvePubkey444",
        real_sol_reserves=50.0,
        virtual_sol_reserves=35.0,
        market_cap_sol=50.0,
        timestamp=1000.0,
    )
    sig_below = engine.evaluate_pre_graduation_harvesting_entry(
        mint, min_progress_pct=70.0, max_progress_pct=85.0
    )
    assert not sig_below.triggered
    assert "progress_outside_window" in sig_below.reason

    # Advance into 75% progress with positive acceleration (50 -> 56 -> 65 SOL, a > 0)
    engine.update_bonding_curve(
        mint=mint,
        bonding_curve="CurvePubkey444",
        real_sol_reserves=56.0,
        virtual_sol_reserves=38.0,
        market_cap_sol=56.0,
        timestamp=1010.0,
    )
    engine.update_bonding_curve(
        mint=mint,
        bonding_curve="CurvePubkey444",
        real_sol_reserves=65.0,
        virtual_sol_reserves=42.0,
        market_cap_sol=65.0,
        timestamp=1020.0,
    )

    sig_entry = engine.evaluate_pre_graduation_harvesting_entry(
        mint,
        min_progress_pct=70.0,
        max_progress_pct=85.0,
        min_acceleration=0.0,
        current_time=1020.0,
    )
    assert sig_entry.triggered
    assert sig_entry.stage == "pre_graduation"
    assert "pre_graduation_acceleration_surge" in sig_entry.reason


def test_pre_graduation_staged_take_profit_tranches():
    config = TradingBotConfig(
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
    return TradingBotConfig(
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
