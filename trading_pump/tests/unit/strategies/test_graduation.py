"""Unit tests for ``strategies/graduation.py``."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from trading_pump.strategies.graduation import (
    GraduationCandidate,
    GraduationEngine,
    GraduationSignal,
    GraduationTracker,
    GraduationTrajectory,
    RaydiumPoolKeys,
)
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_pool_keys


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


def test_raydium_pool_keys_to_and_from_dict():
    keys = make_pool_keys(
        "TestMint1111111111111111111111111111111111",
        amm_id="RaydiumAmm1111111111111111111111111111111111",
    )
    d = keys.to_dict()
    assert d["amm_id"] == "RaydiumAmm1111111111111111111111111111111111"
    assert d["coin_mint"] == "TestMint1111111111111111111111111111111111"
    assert d["pc_mint"] == "So11111111111111111111111111111111111111112"

    restored = RaydiumPoolKeys.from_dict(d)
    assert restored.amm_id == keys.amm_id
    assert restored.serum_market == keys.serum_market
    assert restored.lp_mint == keys.lp_mint


def test_graduation_candidate_model_and_dict():
    cand = GraduationCandidate(
        mint="MintA1111111111111111111111111111111111111",
        bonding_curve="CurveA111111111111111111111111111111111111",
        real_sol_reserves=42.5,
        virtual_sol_reserves=72.5,
        market_cap_sol=50.0,
        progress_pct=50.0,
    )
    d = cand.to_dict()
    assert d["mint"] == "MintA1111111111111111111111111111111111111"
    assert d["real_sol_reserves"] == 42.5
    assert d["progress_pct"] == 50.0
    assert d["is_completed"] is False
    assert d["pool_keys"] is None


def test_graduation_tracker_lifecycle_and_signals():
    tracker = GraduationTracker(
        mint="MintB1111111111111111111111111111111111111",
        bonding_curve="CurveB111111111111111111111111111111111111",
        real_sol_reserves=10.0,
        virtual_sol_reserves=40.0,
        market_cap_sol=35.0,
        target_graduation_sol=85.0,
        timestamp=1000.0,
    )

    # Initial state (10 SOL / 85 SOL ≈ 11.76%)
    assert tracker.candidate.progress_pct == 11.76
    sig_init = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_init.triggered is False
    assert sig_init.stage == "none"

    # Update reserves to 81.0 SOL (Pre-graduation trigger)
    tracker.update_reserves(
        real_sol_reserves=81.0,
        virtual_sol_reserves=111.0,
        market_cap_sol=65.0,
        timestamp=1010.0,
    )
    assert tracker.candidate.progress_pct == 95.29
    sig_pre = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_pre.triggered is True
    assert sig_pre.stage == "pre_graduation"
    assert sig_pre.real_sol_reserves == 81.0

    # With require_pool_ready=True, pre-graduation should not fire
    sig_pre_strict = tracker.evaluate_signal(
        pre_migration_threshold_sol=80.0, require_pool_ready=True
    )
    assert sig_pre_strict.triggered is False
    assert sig_pre_strict.stage == "pre_graduation"

    # Mark curve as completed
    tracker.mark_completed(timestamp=1020.0)
    assert tracker.candidate.is_completed is True
    assert tracker.candidate.completed_at == 1020.0
    assert tracker.candidate.progress_pct == 100.0

    sig_completed = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_completed.triggered is True
    assert sig_completed.stage == "graduated"

    # Set Raydium pool keys
    pool_keys = make_pool_keys(mint="MintB1111111111111111111111111111111111111")
    tracker.set_raydium_pool(pool_keys, timestamp=1030.0)
    assert tracker.candidate.raydium_pool_id == pool_keys.amm_id
    assert tracker.candidate.pool_keys == pool_keys

    sig_ready = tracker.evaluate_signal(
        pre_migration_threshold_sol=80.0, require_pool_ready=True
    )
    assert sig_ready.triggered is True
    assert sig_ready.stage == "raydium_pool_ready"
    assert sig_ready.pool_keys is not None
    assert sig_ready.pool_keys.amm_id == pool_keys.amm_id


def test_graduation_engine_multi_token_management():
    engine = GraduationEngine(
        target_graduation_sol=85.0,
        candidate_ttl_seconds=300,
        pre_migration_threshold_sol=80.0,
    )

    t0 = 1000.0
    engine.update_bonding_curve(
        mint="Token11111111111111111111111111111111111111",
        bonding_curve="Curve11111111111111111111111111111111111111",
        real_sol_reserves=50.0,
        virtual_sol_reserves=80.0,
        market_cap_sol=55.0,
        timestamp=t0,
    )
    engine.update_bonding_curve(
        mint="Token22222222222222222222222222222222222222",
        bonding_curve="Curve22222222222222222222222222222222222222",
        real_sol_reserves=82.5,
        virtual_sol_reserves=112.5,
        market_cap_sol=68.0,
        timestamp=t0,
    )

    assert engine.tracked_candidate_count == 2
    c1 = engine.get_candidate("Token11111111111111111111111111111111111111")
    assert c1 is not None
    assert c1.progress_pct == round((50.0 / 85.0) * 100.0, 2)

    sig1 = engine.evaluate_graduation_signal(
        "Token11111111111111111111111111111111111111"
    )
    assert sig1.triggered is False

    sig2 = engine.evaluate_graduation_signal(
        "Token22222222222222222222222222222222222222"
    )
    assert sig2.triggered is True
    assert sig2.stage == "pre_graduation"

    # Untracked token evaluation
    sig_untracked = engine.evaluate_graduation_signal(
        "UnknownMint1111111111111111111111111111111"
    )
    assert sig_untracked.triggered is False
    assert sig_untracked.reason == "candidate_not_tracked"

    # Record complete event
    engine.record_complete_event(
        "Token22222222222222222222222222222222222222", timestamp=t0 + 10
    )
    c2 = engine.get_candidate("Token22222222222222222222222222222222222222")
    assert c2.is_completed is True

    # Record Raydium pool initialization
    keys2 = make_pool_keys("Token22222222222222222222222222222222222222")
    engine.record_raydium_pool(
        "Token22222222222222222222222222222222222222", keys2, timestamp=t0 + 20
    )

    sig2_pool = engine.evaluate_graduation_signal(
        "Token22222222222222222222222222222222222222"
    )
    assert sig2_pool.triggered is True
    assert sig2_pool.stage == "raydium_pool_ready"
    assert sig2_pool.pool_keys is not None


def test_graduation_engine_ttl_cleanup_and_clear():
    engine = GraduationEngine(candidate_ttl_seconds=100)
    t0 = 500.0

    engine.update_bonding_curve(
        mint="StaleMint111111111111111111111111111111111111",
        bonding_curve="StaleCurve111111111111111111111111111111111",
        real_sol_reserves=20.0,
        virtual_sol_reserves=50.0,
        market_cap_sol=35.0,
        timestamp=t0,
    )
    engine.update_bonding_curve(
        mint="FreshMint111111111111111111111111111111111111",
        bonding_curve="FreshCurve111111111111111111111111111111111",
        real_sol_reserves=70.0,
        virtual_sol_reserves=100.0,
        market_cap_sol=55.0,
        timestamp=t0 + 80,
    )

    assert engine.tracked_candidate_count == 2

    # Cleanup at t0 + 120 (StaleMint updated at 500 -> 620-500 = 120 > 100 => evicted)
    evicted = engine.cleanup_expired_candidates(current_time=t0 + 120)
    assert evicted == 1
    assert engine.tracked_candidate_count == 1
    assert engine.get_candidate("StaleMint111111111111111111111111111111111111") is None
    assert (
        engine.get_candidate("FreshMint111111111111111111111111111111111111")
        is not None
    )

    engine.clear()
    assert engine.tracked_candidate_count == 0


def test_graduation_and_api_client_deep():
    from trading_pump.api.client import PumpFunApiClient
    from trading_pump.strategies.graduation import (
        GraduationEngine,
        GraduationTracker,
    )

    # GraduationSignal to_dict
    sig = GraduationSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        stage="graduated",
        market_cap_sol=85.0,
        real_sol_reserves=85.0,
        pool_keys=make_pool_keys(unique=False),
        reason="graduated_ready",
    )
    d = sig.to_dict()
    assert d["triggered"] is True
    assert d["pool_keys"] is not None

    # GraduationTracker mark_completed
    tracker = GraduationTracker(mint=SAMPLE_MINT, target_graduation_sol=85.0)
    tracker.update_reserves(85.0, 115.0, 85.0, complete=True)
    assert tracker.candidate.is_completed is True
    assert tracker.candidate.progress_pct == 100.0

    # GraduationEngine cleanup_expired_candidates
    engine = GraduationEngine(candidate_ttl_seconds=1)
    engine.update_bonding_curve(SAMPLE_MINT, "curve1", 50.0, 100.0, 50.0)
    engine._trackers[SAMPLE_MINT].candidate.updated_at = time.time() - 10.0
    pruned = engine.cleanup_expired_candidates()
    assert pruned == 1
    assert SAMPLE_MINT not in engine._trackers

    # ApiClient get_creator_coins with empty creator
    api = PumpFunApiClient()
    api.get_creator_coins = AsyncMock(return_value=[])
    # test close
    # synchronous check
    assert api is not None


def test_graduation_trajectory_and_signals():
    from trading_pump.strategies.graduation import (
        GraduationEngine,
        GraduationTracker,
    )

    tracker = GraduationTracker(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        bonding_curve="Curve111",
        real_sol_reserves=50.0,
        virtual_sol_reserves=80.0,
        market_cap_sol=45.0,
        timestamp=time.time() - 30.0,
    )

    # Classify organic accumulation trajectory
    tracker.update_reserves(
        real_sol_reserves=60.0,
        virtual_sol_reserves=90.0,
        market_cap_sol=55.0,
        timestamp=time.time() - 15.0,
    )
    tracker.update_reserves(
        real_sol_reserves=72.0,
        virtual_sol_reserves=102.0,
        market_cap_sol=65.0,
        timestamp=time.time(),
    )

    traj = tracker.classify_trajectory(unique_buyers=3)
    assert traj.mint == "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    assert traj.progress_pct > 0.0

    # Signal evaluation without tracker in engine
    engine = GraduationEngine()
    sig = engine.evaluate_graduation_signal("non_existent_mint")
    assert sig.triggered is False

    traj_none = engine.evaluate_graduation_trajectory("non_existent_mint")
    assert traj_none is None


def test_polled_curves_need_enough_readings_before_a_pre_graduation_entry() -> None:
    """FEAT-53: one or two polls give acceleration 0 by construction."""
    engine = GraduationEngine(target_graduation_sol=85.0)
    for i, real_sol in enumerate([64.0, 64.5, 65.5, 67.0]):
        engine.update_bonding_curve(
            mint="polled",
            bonding_curve="",
            real_sol_reserves=real_sol,
            virtual_sol_reserves=30.0 + real_sol,
            market_cap_sol=70.0,
            timestamp=100.0 + 2 * i,
        )
    tracker = engine._trackers["polled"]
    assert tracker.sample_count(current_time=106.0) == 4
    assert tracker.sample_count(window_seconds=3.0, current_time=106.0) == 2

    kwargs: dict[str, Any] = {
        "min_progress_pct": 75.0,
        "max_progress_pct": 88.0,
        "current_time": 106.0,
    }
    short = engine.evaluate_pre_graduation_harvesting_entry(
        "polled", min_samples=5, **kwargs
    )
    assert not short.triggered
    assert short.reason.startswith("insufficient_history")

    enough = engine.evaluate_pre_graduation_harvesting_entry(
        "polled", min_samples=4, **kwargs
    )
    assert enough.triggered
    assert enough.trajectory is not None
    assert enough.trajectory.acceleration_sol_per_sec2 > 0.0
